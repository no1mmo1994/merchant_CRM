"use client";

import * as React from "react";
import { useFieldArray, useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useCreateModifierGroup } from "@/lib/api/modifiers";

const modifierSchema = z.object({
  name: z.string().min(1, "Required"),
  price_vnd: z.coerce.number().int().min(0, "Must be ≥ 0"),
});

const groupSchema = z.object({
  group_name: z.string().min(1, "Group name required").max(80),
  selection_range_min: z.coerce.number().int().min(0),
  selection_range_max: z.coerce.number().int().min(1),
  modifiers: z.array(modifierSchema).min(1, "Add at least one modifier"),
}).refine((g) => g.selection_range_max >= g.selection_range_min, {
  message: "Max must be ≥ Min",
  path: ["selection_range_max"],
});

type GroupFormValues = z.infer<typeof groupSchema>;

interface ModifierEditorProps {
  /** Called after a successful save with the new group's id + name. */
  onCreated?: (group: { id: string; name: string }) => void;
}

export function ModifierEditor({ onCreated }: ModifierEditorProps) {
  const createGroup = useCreateModifierGroup();
  const form = useForm<GroupFormValues>({
    resolver: zodResolver(groupSchema) as never,
    defaultValues: {
      group_name: "",
      selection_range_min: 0,
      selection_range_max: 1,
      modifiers: [{ name: "", price_vnd: 0 }],
    },
  });
  const { fields, append, remove } = useFieldArray({ control: form.control, name: "modifiers" });

  async function onSubmit(values: GroupFormValues) {
    try {
      const result = await createGroup.mutateAsync({
        group_name: values.group_name,
        selection_range_min: values.selection_range_min,
        selection_range_max: values.selection_range_max,
        modifiers: values.modifiers,
      });
      toast.success(`Created "${result.modifier_group_name}"`);
      onCreated?.({ id: result.modifier_group_id, name: result.modifier_group_name });
      form.reset();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to create modifier group");
    }
  }

  return (
    <Card className="border-(--color-border)">
      <CardHeader>
        <CardTitle>New modifier group</CardTitle>
      </CardHeader>
      <form onSubmit={form.handleSubmit(onSubmit)}>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="group_name">Group name (Vietnamese)</Label>
            <Input id="group_name" placeholder="Size, Topping, Sugar level…" {...form.register("group_name")} />
            {form.formState.errors.group_name && (
              <p className="text-xs text-red-500">{form.formState.errors.group_name.message}</p>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="sel_min">Min selections</Label>
              <Input
                id="sel_min"
                type="number"
                min={0}
                {...form.register("selection_range_min")}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="sel_max">Max selections</Label>
              <Input
                id="sel_max"
                type="number"
                min={1}
                {...form.register("selection_range_max")}
              />
              {form.formState.errors.selection_range_max && (
                <p className="text-xs text-red-500">
                  {form.formState.errors.selection_range_max.message}
                </p>
              )}
            </div>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label>Modifiers</Label>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => append({ name: "", price_vnd: 0 })}
              >
                <Plus className="mr-1.5 h-3.5 w-3.5" />
                Add modifier
              </Button>
            </div>
            <div className="space-y-2">
              {fields.map((field, idx) => (
                <div key={field.id} className="flex items-end gap-2">
                  <div className="flex-1 space-y-1">
                    <Input
                      placeholder="Modifier name (e.g. Large)"
                      {...form.register(`modifiers.${idx}.name`)}
                    />
                    {form.formState.errors.modifiers?.[idx]?.name && (
                      <p className="text-xs text-red-500">
                        {form.formState.errors.modifiers[idx]?.name?.message}
                      </p>
                    )}
                  </div>
                  <div className="w-32 space-y-1">
                    <Input
                      type="number"
                      inputMode="numeric"
                      placeholder="Price"
                      {...form.register(`modifiers.${idx}.price_vnd`)}
                    />
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    onClick={() => remove(idx)}
                    disabled={fields.length <= 1}
                    aria-label="Remove modifier"
                    className="text-red-500 hover:bg-red-500/10 hover:text-red-500"
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              ))}
            </div>
            {form.formState.errors.modifiers?.message && (
              <p className="text-xs text-red-500">{form.formState.errors.modifiers.message}</p>
            )}
          </div>
        </CardContent>
        <CardFooter className="justify-end gap-2">
          <Button type="button" variant="ghost" onClick={() => form.reset()}>
            Reset
          </Button>
          <Button
            type="submit"
            disabled={createGroup.isPending}
            className="bg-(--color-brand) text-white hover:bg-(--color-brand-hover)"
          >
            {createGroup.isPending ? "Creating…" : "Create group"}
          </Button>
        </CardFooter>
      </form>
    </Card>
  );
}

"use client";

import * as React from "react";
import { ImagePlus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useUploadItemImage } from "@/lib/api/menu";
import { toast } from "sonner";

interface ItemImageUploaderProps {
  /** Currently-uploaded image URLs. */
  value: string[];
  onChange: (urls: string[]) => void;
  /** Max number of images accepted. */
  max?: number;
}

/**
 * Drag-or-click image uploader. Uploads each file through
 * `useUploadItemImage` (multipart POST /api/items/upload-image) and
 * appends the returned hosted URL to the controlled `value`.
 */
export function ItemImageUploader({ value, onChange, max = 4 }: ItemImageUploaderProps) {
  const upload = useUploadItemMutation();
  const inputRef = React.useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = React.useState(false);

  async function handleFiles(files: FileList | null) {
    if (!files || !files.length) return;
    const remaining = max - value.length;
    const slice = Array.from(files).slice(0, remaining);
    for (const file of slice) {
      try {
        const { url } = await upload.mutateAsync(file);
        onChange([...value, url]);
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "Upload failed");
      }
    }
  }

  function removeAt(idx: number) {
    const next = value.slice();
    next.splice(idx, 1);
    onChange(next);
  }

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-4 gap-2">
        {value.map((url, idx) => (
          <div
            key={`${url}-${idx}`}
            className="group relative aspect-square overflow-hidden rounded-lg border border-(--color-border)"
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={url} alt="" className="h-full w-full object-cover" />
            <button
              type="button"
              onClick={() => removeAt(idx)}
              className="absolute right-1 top-1 rounded-full bg-black/60 p-1 text-white opacity-0 transition-opacity group-hover:opacity-100"
              aria-label="Remove image"
            >
              <X className="h-3 w-3" />
            </button>
          </div>
        ))}
        {value.length < max && (
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              void handleFiles(e.dataTransfer.files);
            }}
            className={[
              "flex aspect-square flex-col items-center justify-center gap-1 rounded-lg border border-dashed text-xs text-(--color-muted-foreground) transition-colors",
              dragOver
                ? "border-(--color-brand) bg-(--color-brand)/5"
                : "border-(--color-border) hover:bg-(--color-surface-2)",
            ].join(" ")}
          >
            <ImagePlus className="h-5 w-5" />
            <span>Add image</span>
          </button>
        )}
      </div>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        multiple
        className="hidden"
        onChange={(e) => {
          void handleFiles(e.target.files);
          e.target.value = "";
        }}
      />
      {upload.isPending && (
        <div className="text-xs text-(--color-muted-foreground)">Uploading…</div>
      )}
      {value.length > 0 && (
        <div className="flex justify-end">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => onChange([])}
            className="text-red-500 hover:bg-red-500/10 hover:text-red-500"
          >
            Clear all
          </Button>
        </div>
      )}
    </div>
  );
}

// Re-exported so the consumer can call into the same mutation cleanly.
function useUploadItemMutation() {
  return useUploadItemImage();
}

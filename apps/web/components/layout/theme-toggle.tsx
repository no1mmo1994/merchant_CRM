"use client";

import * as React from "react";
import { useTheme } from "next-themes";
import { Monitor, Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

/**
 * Three-option theme switcher: Light / Dark / System.
 *
 * Uses `next-themes` for persistence (localStorage). `mounted` gate
 * prevents hydration mismatch on the icon.
 */
export function ThemeToggle() {
  const { theme, setTheme, resolvedTheme } = useTheme();
  const [mounted, setMounted] = React.useState(false);
  React.useEffect(() => setMounted(true), []);

  const icon = mounted && resolvedTheme === "dark"
    ? <Moon className="h-4 w-4" />
    : <Sun className="h-4 w-4" />;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={(props) => (
          <Button
            {...props}
            variant="ghost"
            size="icon"
            aria-label="Toggle theme"
            className="text-(--color-muted-foreground) hover:text-(--color-foreground)"
          >
            {icon}
          </Button>
        )}
      />
      <DropdownMenuContent align="end" className="w-36">
        <DropdownMenuItem
          onSelect={() => setTheme("light")}
          className="flex items-center gap-2"
          data-active={theme === "light" || undefined}
        >
          <Sun className="h-4 w-4" /> Sáng
        </DropdownMenuItem>
        <DropdownMenuItem
          onSelect={() => setTheme("dark")}
          className="flex items-center gap-2"
          data-active={theme === "dark" || undefined}
        >
          <Moon className="h-4 w-4" /> Tối
        </DropdownMenuItem>
        <DropdownMenuItem
          onSelect={() => setTheme("system")}
          className="flex items-center gap-2"
          data-active={theme === "system" || undefined}
        >
          <Monitor className="h-4 w-4" /> Hệ thống
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
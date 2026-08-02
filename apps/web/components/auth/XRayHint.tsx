"use client";

import * as React from "react";
import { HelpCircle } from "lucide-react";
import { Button } from "@/components/ui/button";

/**
 * Collapsible explainer for the x-ray token. Uses a native `<details>`
 * element so we don't depend on shadcn's Collapsible primitive.
 *
 * Copy-to-clipboard for the exact header name so the user can paste it
 * straight into DevTools' filter box.
 */
export function XRayHint() {
  const [copied, setCopied] = React.useState(false);

  function copy(name: string) {
    void navigator.clipboard.writeText(name);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }

  return (
    <details className="group rounded-lg border border-(--color-border) bg-(--color-surface-2) p-3 text-sm">
      <summary className="flex cursor-pointer list-none items-center gap-2 font-medium text-(--color-foreground) [&::-webkit-details-marker]:hidden">
        <HelpCircle className="h-4 w-4 text-(--color-muted-foreground)" />
        Làm sao để lấy x-ray token?
        <span className="ml-auto text-xs text-(--color-muted-foreground) group-open:hidden">Hiện</span>
        <span className="ml-auto text-xs text-(--color-muted-foreground) hidden group-open:inline">Ẩn</span>
      </summary>

      <ol className="mt-3 space-y-2 pl-1 text-(--color-muted-foreground)">
        <li>
          <span className="mr-2 inline-block w-5 text-right text-xs opacity-70">1.</span>
          Đăng nhập vào{" "}
          <a
            href="https://merchant.grab.com"
            target="_blank"
            rel="noreferrer"
            className="font-medium text-(--color-foreground) underline underline-offset-2"
          >
            merchant.grab.com
          </a>{" "}
          trong tab khác.
        </li>
        <li>
          <span className="mr-2 inline-block w-5 text-right text-xs opacity-70">2.</span>
          Mở DevTools (<kbd className="rounded border px-1 text-xs">F12</kbd>) → tab{" "}
          <strong className="text-(--color-foreground)">Network</strong>.
        </li>
        <li>
          <span className="mr-2 inline-block w-5 text-right text-xs opacity-70">3.</span>
          Trong tab Network, lọc{" "}
          <code className="rounded bg-(--color-surface) px-1 font-mono text-xs">authnv4</code>{" "}
          và nhấn vào POST <code className="rounded bg-(--color-surface) px-1 font-mono text-xs">login</code>. Sao chép giá trị của header này:
          <div className="mt-2 flex items-center gap-2 rounded-md border border-(--color-border) bg-(--color-surface) px-3 py-2">
            <code className="flex-1 font-mono text-xs">x-ray</code>
            <Button
              type="button"
              size="xs"
              variant="outline"
              onClick={() => copy("x-ray")}
              aria-label="Sao chép tên header"
            >
              {copied ? "Đã sao!" : "Sao chép"}
            </Button>
          </div>
        </li>
        <li className="text-xs">
          Token được ký bởi SDK của Grab dựa trên đồng hồ thiết bị tại thời điểm lấy. Nếu đăng nhập
          thất bại với lỗi drift đồng hồ, hãy lấy lại token từ cùng thiết bị sau khi đảm bảo
          đồng hồ thiết bị đúng.
        </li>
      </ol>
    </details>
  );
}

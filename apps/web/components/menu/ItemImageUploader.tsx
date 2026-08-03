"use client";

import * as React from "react";
import { Crop, ImagePlus, X } from "lucide-react";
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

const MAX_FILE_BYTES = 5 * 1024 * 1024; // 5 MB

/**
 * Read a File and resolve to its natural pixel dimensions.
 * Used to validate aspect-ratio client-side before the upload round-trip —
 * Grab's merchant v2 rejects non-square images with 409 ErrImageAspectRatioNotValid.
 */
function readImageDimensions(file: File): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      const dims = { width: img.naturalWidth, height: img.naturalHeight };
      URL.revokeObjectURL(url);
      resolve(dims);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Không đọc được kích thước ảnh — file có thể bị hỏng."));
    };
    img.src = url;
  });
}

/** Load the file into an HTMLImageElement so we can draw it onto a canvas. */
function loadImageElement(file: File): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve(img);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Không đọc được ảnh — file có thể bị hỏng."));
    };
    img.src = url;
  });
}

/**
 * Center-crop a non-square image to a 1:1 square and return a new `File`.
 *
 * The largest square that fits inside the source is taken, centered
 * horizontally and vertically. Output format follows the source: PNG stays
 * PNG (lossless), JPEG/JPG stay JPEG (quality 0.92). The new file's name
 * is derived from the original so the user can still recognise it.
 */
async function cropToSquare(file: File): Promise<File> {
  const img = await loadImageElement(file);
  const side = Math.min(img.naturalWidth, img.naturalHeight);
  const offsetX = Math.floor((img.naturalWidth - side) / 2);
  const offsetY = Math.floor((img.naturalHeight - side) / 2);

  const canvas = document.createElement("canvas");
  canvas.width = side;
  canvas.height = side;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Canvas 2D context không khả dụng trên trình duyệt này.");
  ctx.drawImage(img, offsetX, offsetY, side, side, 0, 0, side, side);

  const isPng = file.type === "image/png" || /\.png$/i.test(file.name);
  const mime = isPng ? "image/png" : "image/jpeg";
  const quality = isPng ? undefined : 0.92;

  const blob: Blob = await new Promise((resolve, reject) => {
    canvas.toBlob(
      (b) => (b ? resolve(b) : reject(new Error("Canvas toBlob trả về null."))),
      mime,
      quality
    );
  });

  const dotIdx = file.name.lastIndexOf(".");
  const baseName = dotIdx > 0 ? file.name.slice(0, dotIdx) : file.name;
  const ext = isPng ? "png" : "jpg";
  return new File([blob], `${baseName}_1x1.${ext}`, { type: mime });
}

interface PendingCrop {
  /** Local temp id for React keying. */
  id: string;
  file: File;
  width: number;
  height: number;
  /** Object URL for the preview tile; revoked when the entry is removed. */
  previewUrl: string;
}

/**
 * Drag-or-click image uploader. Uploads each file through
 * `useUploadItemImage` (multipart POST /api/items/upload-image) and
 * appends the returned hosted URL to the controlled `value`.
 *
 * Pre-upload validation (saves a round-trip + 409 from Grab):
 *   - ≤ 5 MB
 *   - 1:1 aspect ratio (square) — Grab requires this for menu items
 *
 * For non-square images we don't reject outright — we offer an inline
 * "Crop to 1:1 & upload" button so the user can fix it with one click.
 */
export function ItemImageUploader({ value, onChange, max = 4 }: ItemImageUploaderProps) {
  const upload = useUploadItemMutation();
  const inputRef = React.useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = React.useState(false);
  const [pendingCrops, setPendingCrops] = React.useState<PendingCrop[]>([]);

  // Revoke pending-crop preview URLs when the entries leave state.
  React.useEffect(() => {
    return () => {
      pendingCrops.forEach((p) => URL.revokeObjectURL(p.previewUrl));
    };
    // We only want to revoke on unmount — entries that change are
    // explicitly revoked in `removePending` / `commitPending`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function removePending(id: string) {
    setPendingCrops((prev) => {
      const entry = prev.find((p) => p.id === id);
      if (entry) URL.revokeObjectURL(entry.previewUrl);
      return prev.filter((p) => p.id !== id);
    });
  }

  async function commitPending(id: string) {
    const entry = pendingCrops.find((p) => p.id === id);
    if (!entry) return;
    try {
      const cropped = await cropToSquare(entry.file);
      const { url } = await upload.mutateAsync(cropped);
      // Successful upload — drop the pending entry and append the URL.
      URL.revokeObjectURL(entry.previewUrl);
      setPendingCrops((prev) => prev.filter((p) => p.id !== id));
      onChange([...value, url]);
      toast.success(`Đã crop + upload "${cropped.name}"`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Crop hoặc upload thất bại");
    }
  }

  async function handleFiles(files: FileList | null) {
    if (!files || !files.length) return;
    const remaining = max - value.length - pendingCrops.length;
    if (remaining <= 0) {
      toast.error(`Đã đạt tối đa ${max} ảnh.`);
      return;
    }
    const slice = Array.from(files).slice(0, remaining);
    const newPending: PendingCrop[] = [];

    for (const file of slice) {
      if (file.size > MAX_FILE_BYTES) {
        toast.error(
          `Ảnh "${file.name}" quá lớn (${(file.size / 1024 / 1024).toFixed(1)} MB). Tối đa 5 MB.`
        );
        continue;
      }
      let dims: { width: number; height: number };
      try {
        dims = await readImageDimensions(file);
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "Đọc ảnh thất bại");
        continue;
      }
      if (dims.width === dims.height) {
        // Already square — upload directly.
        try {
          const { url } = await upload.mutateAsync(file);
          onChange([...value, url]);
        } catch (err) {
          toast.error(err instanceof Error ? err.message : "Upload failed");
        }
      } else {
        // Non-square — park for the user to crop explicitly.
        newPending.push({
          id: `crop-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          file,
          width: dims.width,
          height: dims.height,
          previewUrl: URL.createObjectURL(file),
        });
      }
    }

    if (newPending.length) {
      setPendingCrops((prev) => [...prev, ...newPending]);
      const names = newPending.map((p) => `"${p.file.name}" (${p.width}×${p.height})`).join(", ");
      toast.info(`Ảnh chưa vuông: ${names}. Bấm "Crop 1:1" để upload.`);
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
        {pendingCrops.map((p) => {
          const side = Math.min(p.width, p.height);
          const offsetXPct = ((p.width - side) / 2 / p.width) * 100;
          const offsetYPct = ((p.height - side) / 2 / p.height) * 100;
          const sizePct = (side / Math.max(p.width, p.height)) * 100;
          return (
            <div
              key={p.id}
              className="group relative aspect-square overflow-hidden rounded-lg border border-amber-500/60 bg-amber-50/30"
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={p.previewUrl}
                alt=""
                className="absolute inset-0 h-full w-full object-cover opacity-60"
              />
              {/* center-crop overlay */}
              <div
                className="absolute inset-0 border-2 border-amber-500"
                style={{
                  left: `${offsetXPct}%`,
                  top: `${offsetYPct}%`,
                  width: `${sizePct}%`,
                  height: `${sizePct}%`,
                }}
              />
              <div className="absolute inset-x-0 bottom-0 flex flex-col gap-0.5 bg-black/70 p-1.5 text-[10px] text-white">
                <div className="truncate font-medium">{p.file.name}</div>
                <div className="text-white/70">
                  {p.width}×{p.height} — vuông sau crop
                </div>
                <button
                  type="button"
                  onClick={() => void commitPending(p.id)}
                  disabled={upload.isPending}
                  className="mt-1 flex items-center justify-center gap-1 rounded bg-amber-500 px-2 py-1 text-[10px] font-semibold text-white hover:bg-amber-600 disabled:opacity-50"
                >
                  <Crop className="h-3 w-3" />
                  Crop 1:1 & upload
                </button>
              </div>
              <button
                type="button"
                onClick={() => removePending(p.id)}
                className="absolute right-1 top-1 rounded-full bg-black/60 p-1 text-white opacity-0 transition-opacity group-hover:opacity-100"
                aria-label="Discard image"
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          );
        })}
        {value.length + pendingCrops.length < max && (
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
      {pendingCrops.length > 0 && (
        <div className="text-[11px] text-amber-700">
          {pendingCrops.length} ảnh chưa vuông — bấm{" "}
          <span className="font-semibold">Crop 1:1 &amp; upload</span> trên từng ảnh.
        </div>
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

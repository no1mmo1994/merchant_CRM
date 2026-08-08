"use client";

import * as React from "react";
import { Megaphone } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * A program image that degrades to a placeholder instead of breaking.
 *
 * Grab's asset URLs fail in ways nothing upstream can prevent: it hands
 * out CloudFront signed links and does not refresh them, so a program's
 * images can all be dead — observed for real, every URL for one program
 * expired ten days before it was rendered. The backend drops the ones it
 * can prove are expired, but that only covers URLs that *say* they
 * expired. A 403 with no `Expires`, a withdrawn asset, a blocked host, or
 * plain packet loss all still land here.
 *
 * So the last line of defence is the browser telling us it failed. On
 * `error` the image is replaced by the same icon an absent URL gets,
 * which is a card that looks intentional rather than one showing a broken
 * image glyph.
 */
export function ProgramImage({
  src,
  className,
  iconClassName,
}: {
  src: string;
  className?: string;
  iconClassName?: string;
}) {
  const [failed, setFailed] = React.useState(false);

  // A different program can reuse this slot as the list re-renders; without
  // resetting, one dead image would poison whatever URL came next.
  React.useEffect(() => {
    setFailed(false);
  }, [src]);

  if (!src || failed) {
    return (
      <div
        className={cn(
          "flex items-center justify-center bg-(--color-surface-3)",
          className,
        )}
      >
        <Megaphone
          className={cn("text-(--color-muted-foreground)", iconClassName)}
        />
      </div>
    );
  }

  return (
    <img
      src={src}
      alt=""
      loading="lazy"
      onError={() => setFailed(true)}
      className={cn("object-cover", className)}
    />
  );
}

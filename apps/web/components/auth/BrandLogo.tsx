import { cn } from "@/lib/utils";

interface BrandLogoProps {
  className?: string;
  /** Pixel height of the icon — wordmark scales to match. */
  size?: number;
  showWordmark?: boolean;
}

/**
 * PulseOrder brand — orange pulsing-wave icon + wordmark.
 * Used in the auth hero (large) and can be reused anywhere.
 *
 * The waveform is two filled sine pulses that hand off: a "p" leading
 * into a "q" — designed to be readable at 24px and dramatic at 96px.
 */
export function BrandLogo({ className, size = 28, showWordmark = true }: BrandLogoProps) {
  return (
    <div className={cn("inline-flex items-center gap-2.5", className)}>
      <svg
        width={size}
        height={size}
        viewBox="0 0 32 32"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        aria-hidden="true"
      >
        <rect width="32" height="32" rx="8" fill="#F26B3A" />
        <path
          d="M6 12 C 8 5, 11 5, 13 12 S 18 19, 20 12 S 25 5, 27 12"
          stroke="white"
          strokeWidth="2.5"
          strokeLinecap="round"
          fill="none"
        />
        <path
          d="M6 22 C 9 16, 12 28, 16 22 S 22 16, 26 22"
          stroke="white"
          strokeWidth="2.5"
          strokeLinecap="round"
          fill="none"
          opacity="0.7"
        />
      </svg>
      {showWordmark && (
        <span
          className="text-base font-semibold tracking-tight text-(--color-foreground)"
          style={{ fontSize: size * 0.55 }}
        >
          PulseOrder
        </span>
      )}
    </div>
  );
}

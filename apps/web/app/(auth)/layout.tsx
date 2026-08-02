import { PulseOrderHero } from "@/components/auth/PulseOrderHero";

/**
 * Auth route group layout. 2-column on lg+: hero on the left, auth
 * surface on the right. Single column on mobile/tablet.
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-svh w-full lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <PulseOrderHero />
      <main className="flex items-center justify-center p-6 sm:p-10">
        <div className="w-full max-w-md">{children}</div>
      </main>
    </div>
  );
}

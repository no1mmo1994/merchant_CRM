import type { Metadata } from "next";
import { Suspense } from "react";
import { LoginForm } from "@/components/auth/LoginForm";
import { LoginBoot } from "@/components/auth/LoginBoot";

export const metadata: Metadata = {
  title: "PulseOrder — Login",
  description: "Sign in to manage your Grab Merchant stores.",
};

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[40vh] items-center justify-center text-(--color-muted-foreground)">
          Loading…
        </div>
      }
    >
      <LoginBoot>
        <LoginForm />
      </LoginBoot>
    </Suspense>
  );
}

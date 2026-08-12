"use client";

import { useEffect, type ReactNode } from "react";
import { useRouter } from "next/navigation";

import { AppShell } from "@/components/shared/AppShell";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/lib/auth-context";

// Plain children prop, not the generated LayoutProps helper: (app) is a route
// group (no URL of its own), so there's no route literal for LayoutProps to
// key params/slots off — see the (auth) 404 investigation for the same fact
// biting the magic-link URL.
export default function AppLayout({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "unauthenticated") {
      router.replace("/login");
    }
  }, [status, router]);

  if (status === "loading") {
    return (
      <div className="flex min-h-screen flex-col gap-4 p-6">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (status === "unauthenticated") {
    return null;
  }

  return <AppShell>{children}</AppShell>;
}

import { Suspense } from "react";

import { VerifyHandler } from "@/components/auth/VerifyHandler";

export default function VerifyPage() {
  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <Suspense
        fallback={<p className="text-sm text-muted-foreground">Verifying your link…</p>}
      >
        <VerifyHandler />
      </Suspense>
    </main>
  );
}

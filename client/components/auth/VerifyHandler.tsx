"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";
import { apiFetch, ApiError } from "@/lib/api-client";
import { useAuth, type AuthUser } from "@/lib/auth-context";

interface MagicLinkVerifyResponse {
  access_token: string;
  token_type: "bearer";
  user: AuthUser;
}

export function VerifyHandler() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { setAuth } = useAuth();
  const token = searchParams.get("token");
  const hasRun = useRef(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(
    token ? null : "This link is missing its token."
  );

  useEffect(() => {
    if (!token || hasRun.current) return;
    hasRun.current = true;

    apiFetch<MagicLinkVerifyResponse>("/auth/magic-link/verify", {
      method: "POST",
      body: { token },
    })
      .then((response) => {
        setAuth(response.access_token, response.user);
        router.push("/trips");
      })
      .catch((error) => {
        setErrorMessage(
          error instanceof ApiError ? error.message : "Something went wrong verifying this link."
        );
      });
  }, [token, setAuth, router]);

  if (errorMessage) {
    return (
      <div className="flex flex-col items-center gap-4 text-center">
        <p className="text-sm text-destructive">{errorMessage}</p>
        <Link href="/login" className={buttonVariants({ variant: "outline" })}>
          Back to login
        </Link>
      </div>
    );
  }

  return <p className="text-center text-sm text-muted-foreground">Verifying your link…</p>;
}

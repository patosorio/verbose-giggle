"use client";

import { useMutation } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";
import type { AdvisorTurnIn, AdvisorTurnResponse } from "@/lib/types";

export function useAdvisorTurn() {
  const { accessToken } = useAuth();

  return useMutation({
    mutationFn: (body: AdvisorTurnIn) =>
      apiFetch<AdvisorTurnResponse>("/advisor/messages", {
        method: "POST",
        body,
        token: accessToken,
      }),
  });
}

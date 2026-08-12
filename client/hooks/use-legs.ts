"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";
import type {
  LegOut,
  LegPatchIn,
  LockIn,
  LockOut,
  OptionCardOut,
  PriceAdjustIn,
} from "@/lib/types";

export function useLegOptions(legId: string, opts?: { poll?: boolean }) {
  const { accessToken, status } = useAuth();

  return useQuery({
    queryKey: ["legs", legId, "options"],
    queryFn: () =>
      apiFetch<OptionCardOut[]>(`/legs/${legId}/options`, { token: accessToken }),
    enabled: status === "authenticated" && !!accessToken && !!legId,
    refetchInterval: opts?.poll ? 4000 : false,
  });
}

export function usePatchLeg(tripId: string) {
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ legId, body }: { legId: string; body: LegPatchIn }) =>
      apiFetch<LegOut>(`/legs/${legId}`, {
        method: "PATCH",
        body,
        token: accessToken,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["trips", tripId, "legs"] });
    },
  });
}

export function useLockLeg(tripId: string, legId: string) {
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (optionCardId: string) =>
      apiFetch<LockOut>(`/legs/${legId}/lock`, {
        method: "POST",
        body: { option_card_id: optionCardId } satisfies LockIn,
        token: accessToken,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["trips", tripId, "budget"] });
      queryClient.invalidateQueries({ queryKey: ["trips", tripId, "legs"] });
    },
  });
}

export function useUnlockLeg(tripId: string, legId: string) {
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (optionCardId: string) =>
      apiFetch<undefined>(`/legs/${legId}/lock/${optionCardId}`, {
        method: "DELETE",
        token: accessToken,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["trips", tripId, "budget"] });
      queryClient.invalidateQueries({ queryKey: ["trips", tripId, "legs"] });
    },
  });
}

export function useSetBooked(tripId: string, legId: string) {
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (vars: { optionCardId: string; isBooked: boolean }) =>
      apiFetch<LockOut>(`/legs/${legId}/lock/${vars.optionCardId}/booked`, {
        method: "PATCH",
        body: { is_booked: vars.isBooked },
        token: accessToken,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["trips", tripId, "budget"] });
    },
  });
}

export function useAdjustLockPrice(tripId: string) {
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (vars: {
      legId: string;
      optionCardId: string;
      body: PriceAdjustIn;
    }) =>
      apiFetch<LockOut>(
        `/legs/${vars.legId}/lock/${vars.optionCardId}/price`,
        {
          method: "PATCH",
          body: vars.body,
          token: accessToken,
        }
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["trips", tripId, "budget"] });
    },
  });
}

"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";
import type {
  BudgetOut,
  LegBulkCreateIn,
  LegOut,
  ResearchRunType,
  ResearchStartOut,
  TravelerCreateIn,
  TravelerOut,
  TripCreateIn,
  TripMemberCreateIn,
  TripMemberOut,
  TripOut,
  TripPatchIn,
  TripSummaryOut,
} from "@/lib/types";

export function useTrips() {
  const { accessToken, status } = useAuth();

  return useQuery({
    queryKey: ["trips"],
    queryFn: () => apiFetch<TripSummaryOut[]>("/trips", { token: accessToken }),
    enabled: status === "authenticated" && !!accessToken,
  });
}

export function useCreateTrip() {
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (body: TripCreateIn) =>
      apiFetch<TripOut>("/trips", {
        method: "POST",
        body,
        token: accessToken,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["trips"] });
    },
  });
}

export function useTrip(tripId: string) {
  const { accessToken, status } = useAuth();

  return useQuery({
    queryKey: ["trips", tripId],
    queryFn: () => apiFetch<TripOut>(`/trips/${tripId}`, { token: accessToken }),
    enabled: status === "authenticated" && !!accessToken && !!tripId,
  });
}

export function useTripTravelers(tripId: string) {
  const { accessToken, status } = useAuth();

  return useQuery({
    queryKey: ["trips", tripId, "travelers"],
    queryFn: () =>
      apiFetch<TravelerOut[]>(`/trips/${tripId}/travelers`, { token: accessToken }),
    enabled: status === "authenticated" && !!accessToken && !!tripId,
  });
}

export function useTripLegs(tripId: string) {
  const { accessToken, status } = useAuth();

  return useQuery({
    queryKey: ["trips", tripId, "legs"],
    queryFn: () => apiFetch<LegOut[]>(`/trips/${tripId}/legs`, { token: accessToken }),
    enabled: status === "authenticated" && !!accessToken && !!tripId,
    // docs/03_api_contracts.md §5 — poll while research is in flight so the UI
    // leaves "pending"/"researching" without a hard refresh.
    refetchInterval: (query) => {
      const legs = query.state.data;
      if (!legs?.some((leg) => leg.status === "researching")) {
        return false;
      }
      return 4000;
    },
  });
}

export function useTripBudget(tripId: string) {
  const { accessToken, status } = useAuth();

  return useQuery({
    queryKey: ["trips", tripId, "budget"],
    queryFn: () => apiFetch<BudgetOut>(`/trips/${tripId}/budget`, { token: accessToken }),
    enabled: status === "authenticated" && !!accessToken && !!tripId,
  });
}

export function useBulkCreateLegs(tripId: string) {
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (body: LegBulkCreateIn) =>
      apiFetch<LegOut[]>(`/trips/${tripId}/legs:bulk`, {
        method: "POST",
        body,
        token: accessToken,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["trips", tripId, "legs"] });
      queryClient.invalidateQueries({ queryKey: ["trips", tripId, "budget"] });
    },
  });
}

export function useStartResearch(tripId: string) {
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      legId,
      run_type,
    }: {
      legId: string;
      run_type: ResearchRunType;
    }) =>
      apiFetch<ResearchStartOut>(`/legs/${legId}/research`, {
        method: "POST",
        body: { run_type },
        token: accessToken,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["trips", tripId, "legs"] });
    },
  });
}

export function useAddTraveler(tripId: string) {
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: TravelerCreateIn) =>
      apiFetch<TravelerOut>(`/trips/${tripId}/travelers`, {
        method: "POST",
        body: data,
        token: accessToken,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["trips", tripId, "travelers"] });
    },
  });
}

export function useDeleteTraveler(tripId: string) {
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (travelerId: string) =>
      apiFetch<void>(`/trips/${tripId}/travelers/${travelerId}`, {
        method: "DELETE",
        token: accessToken,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["trips", tripId, "travelers"] });
    },
  });
}

export function usePatchTrip(tripId: string) {
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (body: TripPatchIn) =>
      apiFetch<TripOut>(`/trips/${tripId}`, {
        method: "PATCH",
        body,
        token: accessToken,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["trips"] });
      queryClient.invalidateQueries({ queryKey: ["trips", tripId] });
      queryClient.invalidateQueries({ queryKey: ["trips", tripId, "budget"] });
    },
  });
}

export function useDeleteTrip() {
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (tripId: string) =>
      apiFetch<void>(`/trips/${tripId}`, {
        method: "DELETE",
        token: accessToken,
      }),
    onSuccess: (_data, tripId) => {
      queryClient.invalidateQueries({ queryKey: ["trips"] });
      queryClient.removeQueries({ queryKey: ["trips", tripId] });
    },
  });
}

export function useTripMembers(tripId: string) {
  const { accessToken, status } = useAuth();

  return useQuery({
    queryKey: ["trips", tripId, "members"],
    queryFn: () =>
      apiFetch<TripMemberOut[]>(`/trips/${tripId}/members`, { token: accessToken }),
    enabled: status === "authenticated" && !!accessToken && !!tripId,
  });
}

export function useInviteMember(tripId: string) {
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (body: TripMemberCreateIn) =>
      apiFetch<TripMemberOut>(`/trips/${tripId}/members`, {
        method: "POST",
        body,
        token: accessToken,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["trips", tripId, "members"] });
    },
  });
}

export function useRemoveMember(tripId: string) {
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (memberId: string) =>
      apiFetch<void>(`/trips/${tripId}/members/${memberId}`, {
        method: "DELETE",
        token: accessToken,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["trips", tripId, "members"] });
    },
  });
}

"use client";

import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";
import type {
  CitationOut,
  ImportedOptionOut,
  ManualOptionIn,
  OptionCardOut,
  OptionSourcesOut,
  ReactionIn,
  ReactionSummaryOut,
  ReactionType,
} from "@/lib/types";

interface ReactionMutationContext {
  previous: OptionCardOut[] | undefined;
}

function optionsQueryKey(legId: string) {
  return ["legs", legId, "options"] as const;
}

function patchOptionSummary(
  queryClient: QueryClient,
  legId: string,
  optionId: string,
  summary: ReactionSummaryOut
) {
  queryClient.setQueryData<OptionCardOut[]>(optionsQueryKey(legId), (options) =>
    options?.map((option) =>
      option.id === optionId ? { ...option, reaction_summary: summary } : option
    )
  );
}

// Local-only summary the instant a reaction is clicked (docs/04_build_plan.md Phase 6 —
// reactions are optimistic, low-stakes). The real ReactionSummaryOut from the response
// replaces this in onSuccess; onError rolls back to the pre-click snapshot.
function optimisticSummary(
  current: ReactionSummaryOut,
  nextReaction: ReactionType | null
): ReactionSummaryOut {
  let up = current.up;
  let down = current.down;
  if (current.my_reaction === "up") up -= 1;
  if (current.my_reaction === "down") down -= 1;
  if (nextReaction === "up") up += 1;
  if (nextReaction === "down") down += 1;
  return { up, down, my_reaction: nextReaction };
}

export function useSetReaction(legId: string) {
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();
  const queryKey = optionsQueryKey(legId);

  return useMutation<
    ReactionSummaryOut,
    Error,
    { optionId: string; reactionType: ReactionType },
    ReactionMutationContext
  >({
    mutationFn: ({ optionId, reactionType }) =>
      apiFetch<ReactionSummaryOut>(`/options/${optionId}/reactions`, {
        method: "POST",
        body: { reaction_type: reactionType } satisfies ReactionIn,
        token: accessToken,
      }),
    onMutate: async ({ optionId, reactionType }) => {
      await queryClient.cancelQueries({ queryKey });
      const previous = queryClient.getQueryData<OptionCardOut[]>(queryKey);
      const current = previous?.find((option) => option.id === optionId)?.reaction_summary;
      if (current) {
        patchOptionSummary(queryClient, legId, optionId, optimisticSummary(current, reactionType));
      }
      return { previous };
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) {
        queryClient.setQueryData(queryKey, context.previous);
      }
    },
    onSuccess: (summary, { optionId }) => patchOptionSummary(queryClient, legId, optionId, summary),
  });
}

export function useRemoveReaction(legId: string) {
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();
  const queryKey = optionsQueryKey(legId);

  return useMutation<ReactionSummaryOut, Error, string, ReactionMutationContext>({
    mutationFn: (optionId) =>
      apiFetch<ReactionSummaryOut>(`/options/${optionId}/reactions`, {
        method: "DELETE",
        token: accessToken,
      }),
    onMutate: async (optionId) => {
      await queryClient.cancelQueries({ queryKey });
      const previous = queryClient.getQueryData<OptionCardOut[]>(queryKey);
      const current = previous?.find((option) => option.id === optionId)?.reaction_summary;
      if (current) {
        patchOptionSummary(queryClient, legId, optionId, optimisticSummary(current, null));
      }
      return { previous };
    },
    onError: (_err, _optionId, context) => {
      if (context?.previous) {
        queryClient.setQueryData(queryKey, context.previous);
      }
    },
    onSuccess: (summary, optionId) => patchOptionSummary(queryClient, legId, optionId, summary),
  });
}

export function useCreateManualOption(legId: string) {
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (body: ManualOptionIn) =>
      apiFetch<ImportedOptionOut>(`/legs/${legId}/options/manual`, {
        method: "POST",
        body,
        token: accessToken,
      }),
    onSuccess: async () => {
      // Await so the caller can switch to the typed tab after presentTypes refreshes.
      await queryClient.invalidateQueries({ queryKey: optionsQueryKey(legId) });
    },
  });
}

export function useOptionSources(optionId: string, enabled: boolean) {
  const { accessToken, status } = useAuth();

  return useQuery({
    queryKey: ["options", optionId, "sources"],
    queryFn: () =>
      apiFetch<OptionSourcesOut>(`/options/${optionId}/sources`, { token: accessToken }),
    enabled: enabled && status === "authenticated" && !!accessToken && !!optionId,
  });
}

export function useOptionCitations(optionId: string, enabled: boolean) {
  const { accessToken, status } = useAuth();

  return useQuery({
    queryKey: ["options", optionId, "citations"],
    queryFn: () =>
      apiFetch<CitationOut[]>(`/options/${optionId}/citations`, { token: accessToken }),
    enabled: enabled && status === "authenticated" && !!accessToken && !!optionId,
  });
}

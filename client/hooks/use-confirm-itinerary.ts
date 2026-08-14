"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import type { UseFormSetError } from "react-hook-form";
import { toast } from "sonner";

import {
  aiPlannerConfirmFormSchema,
  type AiPlannerFormValues,
} from "@/components/trips/ai-planner-types";
import { useCreateTrip } from "@/hooks/use-trips";
import { apiFetch, ApiError } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";
import { formLegToApiFilters } from "@/lib/leg-filters-map";
import type { LegCreateIn, LegOut, ResearchStartOut } from "@/lib/types";

function buildLegCreateFilters(
  leg: AiPlannerFormValues["legs"][number]
): LegCreateIn["filters"] {
  return formLegToApiFilters(leg);
}

export function useConfirmItinerary() {
  const router = useRouter();
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();
  const createTrip = useCreateTrip();
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function confirm(
    values: AiPlannerFormValues,
    setError: UseFormSetError<AiPlannerFormValues>
  ): Promise<void> {
    const parsed = aiPlannerConfirmFormSchema.safeParse(values);
    if (!parsed.success) {
      for (const issue of parsed.error.issues) {
        const path = issue.path.join(".") as
          | "name"
          | "home_currency"
          | "budget_band"
          | "budget_target_amount"
          | `legs.${number}.origin`
          | `legs.${number}.destination`
          | `legs.${number}.start_date`
          | `legs.${number}.end_date`
          | `legs.${number}.origin_iata`
          | `legs.${number}.destination_iata`;
        setError(path, { message: issue.message });
      }
      toast.error("Fix the highlighted fields before confirming.");
      return;
    }

    const trimmedTarget = parsed.data.budget_target_amount?.trim() ?? "";
    const budgetTarget =
      trimmedTarget === "" ? null : Number(trimmedTarget);
    if (budgetTarget !== null && Number.isNaN(budgetTarget)) {
      toast.error("Budget target must be a number.");
      return;
    }

    setIsSubmitting(true);
    try {
      const trip = await createTrip.mutateAsync({
        name: parsed.data.name,
        home_currency: parsed.data.home_currency,
        budget_band: parsed.data.budget_band,
        budget_target_amount: budgetTarget,
      });

      const body = {
        legs: parsed.data.legs.map((leg, index) => ({
          sequence_index: index,
          origin: leg.origin.trim(),
          destination: leg.destination.trim(),
          origin_iata: leg.origin_iata,
          destination_iata: leg.destination_iata,
          start_date: leg.start_date,
          end_date: leg.end_date,
          skip_hotel: leg.skip_hotel,
          skip_flight: leg.skip_flight,
          filters: buildLegCreateFilters(leg),
        })),
      };

      const created = await apiFetch<LegOut[]>(`/trips/${trip.id}/legs:bulk`, {
        method: "POST",
        body,
        token: accessToken,
      });

      const researchResults = await Promise.allSettled(
        created.map((leg) =>
          apiFetch<ResearchStartOut>(`/legs/${leg.id}/research`, {
            method: "POST",
            body: { run_type: "full" },
            token: accessToken,
          })
        )
      );

      await queryClient.invalidateQueries({ queryKey: ["trips", trip.id] });
      await queryClient.invalidateQueries({
        queryKey: ["trips", trip.id, "legs"],
      });

      const failedCount = researchResults.filter(
        (r) => r.status === "rejected"
      ).length;
      toast.success(
        failedCount > 0
          ? `Trip created — research couldn't start for ${failedCount} leg(s); retry from the leg page`
          : "Trip created — research started"
      );
      router.push(`/trips/${trip.id}`);
    } catch (error) {
      toast.error(
        error instanceof ApiError
          ? error.message
          : "Could not create the trip. Try again."
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return { confirm, isConfirming: isSubmitting || createTrip.isPending };
}

"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { AdvisorChatPanel } from "@/components/trips/AdvisorChatPanel";
import { ItineraryBuilder } from "@/components/trips/ItineraryBuilder";
import {
  AI_PLANNER_DEFAULTS,
  aiPlannerConfirmFormSchema,
  aiPlannerDraftFormSchema,
  type AiPlannerFormValues,
} from "@/components/trips/ai-planner-types";
import { useCreateTrip } from "@/hooks/use-trips";
import { apiFetch, ApiError } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";
import type {
  AdvisorMessageIn,
  LegCreateIn,
  LegOut,
  ResearchStartOut,
} from "@/lib/types";

function buildLegCreateFilters(
  leg: AiPlannerFormValues["legs"][number]
): LegCreateIn["filters"] {
  const flight: NonNullable<LegCreateIn["filters"]>["flight"] = {};
  if (leg.max_stops !== undefined) flight.max_stops = leg.max_stops;
  if (leg.max_price !== undefined) flight.max_price = leg.max_price;

  const hotel: NonNullable<LegCreateIn["filters"]>["hotel"] = {};
  if (leg.star_class.length > 0) hotel.star_class = leg.star_class;
  if (leg.free_cancellation_only) hotel.free_cancellation_only = true;
  if (leg.hotel_price_min !== undefined && leg.hotel_price_max !== undefined) {
    hotel.price_range = {
      min: leg.hotel_price_min,
      max: leg.hotel_price_max,
    };
  }

  const filters: NonNullable<LegCreateIn["filters"]> = {
    occupancy: {
      rooms: leg.rooms.map((room) => ({
        adults: room.adults,
        children: room.children,
        children_ages: room.children_ages.slice(0, room.children),
      })),
    },
  };
  if (Object.keys(flight).length > 0) filters.flight = flight;
  if (Object.keys(hotel).length > 0) filters.hotel = hotel;
  return filters;
}

export function AiTripPlanner() {
  const router = useRouter();
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();
  const createTrip = useCreateTrip();
  const [messages, setMessages] = useState<AdvisorMessageIn[]>([]);
  const [isConfirming, setIsConfirming] = useState(false);

  const {
    register,
    control,
    handleSubmit,
    getValues,
    reset,
    setValue,
    watch,
    setError,
    formState: { errors },
  } = useForm<AiPlannerFormValues>({
    resolver: zodResolver(aiPlannerDraftFormSchema),
    defaultValues: AI_PLANNER_DEFAULTS,
  });

  async function onConfirm(values: AiPlannerFormValues) {
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

    setIsConfirming(true);
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
      setIsConfirming(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(18rem,22rem)]">
      <ItineraryBuilder
        control={control}
        register={register}
        setValue={setValue}
        watch={watch}
        errors={errors}
        isConfirming={isConfirming || createTrip.isPending}
        onConfirm={() => {
          void handleSubmit(onConfirm)();
        }}
      />
      <AdvisorChatPanel
        getValues={getValues}
        reset={reset}
        messages={messages}
        onMessagesChange={setMessages}
      />
    </div>
  );
}

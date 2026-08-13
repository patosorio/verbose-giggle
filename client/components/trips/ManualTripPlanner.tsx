"use client";

import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";

import { ItineraryBuilder } from "@/components/trips/ItineraryBuilder";
import {
  AI_PLANNER_DEFAULTS,
  aiPlannerDraftFormSchema,
  emptyAiPlannerLeg,
  type AiPlannerFormValues,
} from "@/components/trips/ai-planner-types";
import { useConfirmItinerary } from "@/hooks/use-confirm-itinerary";
import { apiFetch } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";
import type { AirportResolveOut } from "@/lib/types";

const RESOLVE_DEBOUNCE_MS = 400;

export function ManualTripPlanner() {
  const { accessToken } = useAuth();
  const { confirm, isConfirming } = useConfirmItinerary();

  const {
    register,
    control,
    handleSubmit,
    setValue,
    watch,
    setError,
    formState: { errors },
  } = useForm<AiPlannerFormValues>({
    resolver: zodResolver(aiPlannerDraftFormSchema),
    defaultValues: {
      ...AI_PLANNER_DEFAULTS,
      legs: [emptyAiPlannerLeg()],
    },
  });

  useEffect(() => {
    const timers = new Map<string, ReturnType<typeof setTimeout>>();

    const subscription = watch((values, { name }) => {
      if (!name) return;
      const match = /^legs\.(\d+)\.(origin|destination)$/.exec(name);
      if (!match) return;

      const index = Number(match[1]);
      const field = match[2] as "origin" | "destination";
      const place = values.legs?.[index]?.[field]?.trim() ?? "";
      const key = `${index}.${field}`;
      const iataPath =
        field === "origin"
          ? (`legs.${index}.origin_iata` as const)
          : (`legs.${index}.destination_iata` as const);
      const candidatesPath =
        field === "origin"
          ? (`legs.${index}.origin_candidates` as const)
          : (`legs.${index}.destination_candidates` as const);

      const existing = timers.get(key);
      if (existing) clearTimeout(existing);

      if (!place) {
        setValue(iataPath, null);
        setValue(candidatesPath, []);
        return;
      }

      if (!accessToken) return;

      timers.set(
        key,
        setTimeout(() => {
          void (async () => {
            try {
              const result = await apiFetch<AirportResolveOut>(
                `/airports/resolve?place=${encodeURIComponent(place)}`,
                { token: accessToken }
              );
              setValue(iataPath, result.resolved_iata);
              setValue(candidatesPath, result.candidates);
            } catch {
              // Leave prior resolution; user can still pick or retype.
            }
          })();
        }, RESOLVE_DEBOUNCE_MS)
      );
    });

    return () => {
      subscription.unsubscribe();
      for (const timer of timers.values()) clearTimeout(timer);
    };
  }, [accessToken, setValue, watch]);

  return (
    <ItineraryBuilder
      control={control}
      register={register}
      setValue={setValue}
      watch={watch}
      errors={errors}
      isConfirming={isConfirming}
      onConfirm={() => {
        void handleSubmit((values) => confirm(values, setError))();
      }}
    />
  );
}

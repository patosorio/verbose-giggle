"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";

import { AdvisorChatPanel } from "@/components/trips/AdvisorChatPanel";
import { ItineraryBuilder } from "@/components/trips/ItineraryBuilder";
import {
  AI_PLANNER_DEFAULTS,
  aiPlannerDraftFormSchema,
  type AiPlannerFormValues,
} from "@/components/trips/ai-planner-types";
import { useConfirmItinerary } from "@/hooks/use-confirm-itinerary";
import type { AdvisorMessageIn } from "@/lib/types";

export function AiTripPlanner() {
  const { confirm, isConfirming } = useConfirmItinerary();
  const [messages, setMessages] = useState<AdvisorMessageIn[]>([]);

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

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(18rem,22rem)]">
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
      <AdvisorChatPanel
        getValues={getValues}
        reset={reset}
        messages={messages}
        onMessagesChange={setMessages}
      />
    </div>
  );
}

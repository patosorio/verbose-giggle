"use client";

import { useState } from "react";
import type { UseFormGetValues, UseFormReset, UseFormSetValue } from "react-hook-form";
import { toast } from "sonner";

import {
  DEFAULT_LEG_FILTERS,
} from "@/components/legs/LegFiltersFields";
import { AdvisorReplyMarkdown } from "@/components/trips/AdvisorReplyMarkdown";
import {
  chatLinesToApiMessages,
  mergeLockedWithAdvisorLegs,
  type AdvisorChatLine,
  type AiPlannerFormValues,
} from "@/components/trips/ai-planner-types";
import { Button } from "@/components/ui/button";
import { useAdvisorTurn } from "@/hooks/use-advisor";
import { ApiError } from "@/lib/api-client";
import { apiFiltersToFormFields, formLegToApiFilters } from "@/lib/leg-filters-map";
import type {
  AdvisorLegIn,
  AdvisorTurnResponse,
  AirportCandidateOut,
  BudgetBand,
  ProposedLegOut,
} from "@/lib/types";

interface AdvisorChatPanelProps {
  getValues: UseFormGetValues<AiPlannerFormValues>;
  reset: UseFormReset<AiPlannerFormValues>;
  setValue: UseFormSetValue<AiPlannerFormValues>;
  messages: AdvisorChatLine[];
  onMessagesChange: (messages: AdvisorChatLine[]) => void;
}

function buildFiltersFromLeg(
  leg: AiPlannerFormValues["legs"][number]
): AdvisorLegIn["filters"] {
  return formLegToApiFilters(leg);
}

function formLegToAdvisor(
  leg: AiPlannerFormValues["legs"][number]
): AdvisorLegIn {
  return {
    origin: leg.origin.trim(),
    destination: leg.destination.trim(),
    start_date: leg.start_date || null,
    end_date: leg.end_date || null,
    skip_hotel: leg.skip_hotel,
    skip_flight: leg.skip_flight,
    locked: false,
    filters: buildFiltersFromLeg(leg),
  };
}

function proposedToFormLeg(leg: ProposedLegOut): AiPlannerFormValues["legs"][number] {
  const rooms =
    leg.filters?.occupancy?.rooms?.map((room) => ({
      adults: room.adults,
      children: room.children,
      children_ages: room.children_ages ?? [],
    })) ?? [{ ...DEFAULT_LEG_FILTERS.rooms[0], children_ages: [] }];

  return {
    ...DEFAULT_LEG_FILTERS,
    origin: leg.origin,
    destination: leg.destination,
    start_date: leg.start_date ?? "",
    end_date: leg.end_date ?? "",
    origin_iata: leg.origin_iata,
    destination_iata: leg.destination_iata,
    origin_candidates: leg.origin_candidates ?? ([] as AirportCandidateOut[]),
    destination_candidates:
      leg.destination_candidates ?? ([] as AirportCandidateOut[]),
    locked: false,
    rooms,
    skip_hotel: leg.skip_hotel ?? false,
    skip_flight: leg.skip_flight ?? false,
    ...apiFiltersToFormFields(leg.filters),
  };
}

function filledOrCurrent(next: string | null | undefined, current: string): string {
  const trimmed = next?.trim() ?? "";
  return trimmed !== "" ? trimmed : current;
}

function applyAdvisorResponse(
  reset: UseFormReset<AiPlannerFormValues>,
  setValue: UseFormSetValue<AiPlannerFormValues>,
  getValues: UseFormGetValues<AiPlannerFormValues>,
  response: AdvisorTurnResponse,
  legsBefore: AiPlannerFormValues["legs"]
) {
  const current = getValues();
  const targetRaw = response.budget_target_amount;
  const targetStr =
    targetRaw === null || targetRaw === undefined ? "" : String(targetRaw);
  const nextName = filledOrCurrent(response.trip_name, current.name);
  const nextCurrency = filledOrCurrent(
    response.home_currency,
    current.home_currency
  );
  const nextBand = (response.budget_band ?? current.budget_band) as BudgetBand;
  const nextTarget =
    targetStr !== "" ? targetStr : current.budget_target_amount;

  if (response.action !== "revise") {
    setValue("name", nextName);
    setValue("home_currency", nextCurrency);
    setValue("budget_band", nextBand);
    setValue("budget_target_amount", nextTarget);
    return;
  }

  reset({
    name: nextName,
    home_currency: nextCurrency,
    budget_band: nextBand,
    budget_target_amount: nextTarget,
    legs: mergeLockedWithAdvisorLegs(
      legsBefore,
      response.legs.map(proposedToFormLeg)
    ),
  });
}

export function AdvisorChatPanel({
  getValues,
  reset,
  setValue,
  messages,
  onMessagesChange,
}: AdvisorChatPanelProps) {
  const [draft, setDraft] = useState("");
  const advisorTurn = useAdvisorTurn();

  async function onSend() {
    const content = draft.trim();
    if (!content || advisorTurn.isPending) return;

    const values = getValues();
    const legsBefore = values.legs.map((leg) => ({ ...leg }));
    const unlocked = values.legs.filter((leg) => !leg.locked);
    const locked = values.legs.filter((leg) => leg.locked);
    const nextMessages: AdvisorChatLine[] = [
      ...messages,
      { role: "user", content },
    ];
    onMessagesChange(nextMessages);
    setDraft("");

    const trimmedTarget = values.budget_target_amount?.trim() ?? "";
    const budgetTarget =
      trimmedTarget === "" ? null : Number(trimmedTarget);

    try {
      const response = await advisorTurn.mutateAsync({
        messages: chatLinesToApiMessages(nextMessages),
        current_legs: unlocked.map(formLegToAdvisor),
        locked_legs: locked.map(formLegToAdvisor),
        trip_name: values.name.trim() || null,
        home_currency: values.home_currency.trim() || null,
        budget_band: values.budget_band,
        budget_target_amount:
          budgetTarget !== null && !Number.isNaN(budgetTarget)
            ? budgetTarget
            : null,
      });

      applyAdvisorResponse(reset, setValue, getValues, response, legsBefore);
      onMessagesChange([
        ...nextMessages,
        {
          role: "assistant",
          content: response.reply,
          questions: response.questions ?? [],
        },
      ]);
    } catch (error) {
      onMessagesChange(messages);
      setDraft(content);
      toast.error(
        error instanceof ApiError
          ? error.message
          : "Advisor request failed. Try again."
      );
    }
  }

  return (
    <div className="flex h-full min-h-[28rem] flex-col gap-3 rounded-panel border border-border-soft bg-bg p-6 shadow-card">
      <p className="mb-1 flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-[0.12em] text-ink-muted">
        <span className="size-1.5 rounded-full bg-sunshine" />
        Plan with AI
      </p>
      <div className="rounded-[var(--radius-chip)] bg-surface-alt p-3">
        <p className="text-sm text-ink-muted">
          Chat first, then it fills stops when you agree. Lock a leg to keep it
          out of later edits.
        </p>
        {messages.length === 0 ? (
          <p className="mt-2 text-sm text-ink-muted">
            Try “planning a trip to Thailand” — questions first; once you agree,
            it fills the stops.
          </p>
        ) : null}
      </div>

      <ul className="flex flex-1 flex-col gap-2 overflow-y-auto">
        {messages.map((message, index) => (
          <li
            key={`${message.role}-${index}`}
            className={
              message.role === "user"
                ? "self-end max-w-[90%] rounded-[var(--radius-card)] bg-ink px-3 py-2 text-sm text-white"
                : "self-start max-w-[90%] rounded-[var(--radius-card)] border border-border-soft bg-surface-alt px-3 py-2 text-ink"
            }
          >
            {message.role === "user" ? (
              message.content
            ) : (
              <div className="flex flex-col gap-2">
                <AdvisorReplyMarkdown text={message.content} />
                {message.questions && message.questions.length > 0 ? (
                  <ol className="list-decimal space-y-1 pl-4 text-sm">
                    {message.questions.map((question, questionIndex) => (
                      <li key={questionIndex}>{question}</li>
                    ))}
                  </ol>
                ) : null}
              </div>
            )}
          </li>
        ))}
      </ul>

      <div className="flex items-end gap-2">
        <textarea
          className="min-h-[2.75rem] flex-1 resize-none rounded-[var(--radius-chip)] border border-border-interactive bg-bg px-3 py-2 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
          placeholder="Describe the trip, or ask to change a leg…"
          value={draft}
          disabled={advisorTurn.isPending}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void onSend();
            }
          }}
        />
        <Button
          type="button"
          size="sm"
          disabled={advisorTurn.isPending || !draft.trim()}
          onClick={() => void onSend()}
        >
          {advisorTurn.isPending ? "…" : "Send"}
        </Button>
      </div>
    </div>
  );
}

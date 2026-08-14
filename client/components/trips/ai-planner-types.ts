/** Shared form types for the AI itinerary planner (ItineraryBuilder + AdvisorChatPanel). */

import { z } from "zod";

import {
  DEFAULT_LEG_FILTERS,
  legFiltersFieldsSchema,
} from "@/components/legs/LegFiltersFields";
import type { AdvisorMessageIn, AirportCandidateOut, BudgetBand } from "@/lib/types";

const airportCandidateSchema = z.object({
  iata: z.string(),
  name: z.string(),
  city: z.string(),
  country: z.string(),
});

/** Loose shape while chatting / editing — dates and IATA may still be empty. */
export const aiPlannerDraftLegSchema = legFiltersFieldsSchema.extend({
  origin: z.string(),
  destination: z.string(),
  start_date: z.string(),
  end_date: z.string(),
  origin_iata: z.string().length(3).nullable(),
  destination_iata: z.string().length(3).nullable(),
  origin_candidates: z.array(airportCandidateSchema).default([]),
  destination_candidates: z.array(airportCandidateSchema).default([]),
  locked: z.boolean().default(false),
});

export const aiPlannerDraftFormSchema = z.object({
  name: z.string(),
  home_currency: z.string(),
  budget_band: z.enum(["budget", "comfort", "premium"]),
  budget_target_amount: z.string().optional(),
  legs: z.array(aiPlannerDraftLegSchema),
});

/** Strict confirm validation — date/occupancy rules + IATA unless skip_flight. */
export const aiPlannerConfirmLegSchema = aiPlannerDraftLegSchema.superRefine(
  (leg, ctx) => {
    if (!leg.origin.trim()) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Origin is required",
        path: ["origin"],
      });
    }
    if (!leg.destination.trim()) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Destination is required",
        path: ["destination"],
      });
    }
    if (!leg.start_date) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Start date is required",
        path: ["start_date"],
      });
    }
    if (!leg.end_date) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "End date is required",
        path: ["end_date"],
      });
    }
    if (leg.start_date && leg.end_date && leg.end_date < leg.start_date) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "End date must be on or after start date",
        path: ["end_date"],
      });
    }
    if (!leg.skip_flight) {
      if (!leg.origin_iata) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "Resolve origin airport (badge or picker)",
          path: ["origin_iata"],
        });
      }
      if (!leg.destination_iata) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "Resolve destination airport (badge or picker)",
          path: ["destination_iata"],
        });
      }
    }
  }
);

export const aiPlannerConfirmFormSchema = z.object({
  name: z.string().min(1, "Name is required"),
  home_currency: z
    .string()
    .regex(/^[A-Z]{3}$/, "Enter a 3-letter ISO 4217 code (e.g. USD)"),
  budget_band: z.enum(["budget", "comfort", "premium"]),
  budget_target_amount: z.string().optional(),
  legs: z.array(aiPlannerConfirmLegSchema).min(1, "Add at least one leg"),
});

export type AiPlannerFormValues = z.infer<typeof aiPlannerDraftFormSchema>;

export type AiPlannerLegValues = AiPlannerFormValues["legs"][number];

export function emptyAiPlannerLeg(): AiPlannerLegValues {
  return {
    origin: "",
    destination: "",
    start_date: "",
    end_date: "",
    origin_iata: null,
    destination_iata: null,
    origin_candidates: [] as AirportCandidateOut[],
    destination_candidates: [] as AirportCandidateOut[],
    locked: false,
    ...DEFAULT_LEG_FILTERS,
    rooms: [{ adults: 2, children: 0, children_ages: [] }],
  };
}

export const AI_PLANNER_DEFAULTS: AiPlannerFormValues = {
  name: "",
  home_currency: "",
  budget_band: "comfort" as BudgetBand,
  budget_target_amount: "",
  legs: [],
};

/** Option B: merge locked legs (unchanged) with advisor-revised unlocked legs. */
export function mergeLockedWithAdvisorLegs(
  before: AiPlannerFormValues["legs"],
  advisorUnlocked: AiPlannerFormValues["legs"]
): AiPlannerFormValues["legs"] {
  const queue = advisorUnlocked.map((leg) => ({ ...leg, locked: false }));
  const result: AiPlannerFormValues["legs"] = [];

  for (const leg of before) {
    if (leg.locked) {
      result.push({ ...leg, locked: true });
      continue;
    }
    const next = queue.shift();
    if (next !== undefined) {
      result.push(next);
    }
  }

  for (const leftover of queue) {
    result.push(leftover);
  }
  return result;
}

export type AdvisorChatLine = {
  role: "user" | "assistant";
  content: string;
  questions?: string[];
};

export function chatLinesToApiMessages(
  lines: AdvisorChatLine[]
): AdvisorMessageIn[] {
  return lines.map((line) => {
    if (line.role !== "assistant" || !line.questions?.length) {
      return { role: line.role, content: line.content };
    }
    const numbered = line.questions
      .map((question, index) => `${index + 1}. ${question}`)
      .join("\n");
    return { role: "assistant", content: `${line.content}\n\n${numbered}` };
  });
}

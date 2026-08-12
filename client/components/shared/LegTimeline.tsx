import type { LegOut, LegStatus } from "@/lib/types";

// The LegTimeline pill-row component that originally lived in this file was retired in
// docs/18_phase6_app_shell_cursor_prompts.md Prompt 2 (TripRail replaced it as the
// permanent way to navigate between legs — rendering both was duplicate nav UI on the
// same page). This file stays as the shared home for the PillState model below:
// TripRail, BudgetSidebar, and ItineraryPanel all key their own leg-state rendering off
// it, and moving it to a new file would touch all three for no reason.

export type PillState = "not_started" | "researching" | "reviewing" | "locked" | "failed";

export function derivePillState(
  leg: LegOut,
  lockedOptionIds: readonly string[] | null | undefined
): PillState {
  if (lockedOptionIds && lockedOptionIds.length > 0) {
    return "locked";
  }
  switch (leg.status as LegStatus) {
    case "pending":
      return "not_started";
    case "researching":
      return "researching";
    case "failed":
      return "failed";
    case "ready":
      return "reviewing";
  }
}

export const PILL_LABEL: Record<PillState, string> = {
  not_started: "Not started",
  researching: "Researching",
  reviewing: "Reviewing",
  locked: "Locked",
  failed: "Failed",
};

// Fill-based per docs/17_phase6_visual_design_cursor_prompts.md Prompt 2 — no border
// stroke, state reads from the pill's own background/text color. No current caller
// (the pill row that used it was removed in Prompt 2 above), but it's part of the
// exported PillState contract this file promises, so it stays alongside the rest.
export const PILL_FILL_CLASS: Record<PillState, string> = {
  not_started: "bg-surface-alt text-ink",
  researching: "bg-surface-alt text-ink",
  reviewing: "bg-coral-pink text-white shadow-[0_12px_24px_rgba(255,62,142,0.28)]",
  locked: "bg-deep-ocean text-white",
  // failed has no mockup treatment (docs/07_design_spec.md §5 flag) — low-alarm
  // destructive tint consistent with the rest of the fill-based system.
  failed: "bg-destructive/10 text-destructive",
};

// Every LegOut already carries a backend-computed `nights` count. A flight leg
// (both IATA codes set) has no duration field to show, so "day span" derived
// from nights+1 is the cleanest non-fabricated stand-in for the mockup's
// "Flights · 1 day" treatment.
export function legDetailLine(leg: LegOut): string {
  const isFlightLeg = Boolean(leg.origin_iata && leg.destination_iata);
  if (isFlightLeg) {
    const days = leg.nights + 1;
    return `Flights · ${days === 1 ? "1 day" : `${days} days`}`;
  }
  return leg.nights === 1 ? "1 night" : `${leg.nights} nights`;
}

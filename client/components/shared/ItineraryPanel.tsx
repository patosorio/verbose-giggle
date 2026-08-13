import Link from "next/link";

import { derivePillState, PILL_LABEL } from "@/components/shared/LegTimeline";
import { formatCurrency } from "@/lib/format";
import type { BudgetOut, LegOut } from "@/lib/types";
import { cn } from "@/lib/utils";

export function formatDateShort(iso: string): string {
  const date = new Date(`${iso}T00:00:00Z`);
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(date);
}

interface ItineraryPanelProps {
  legs: LegOut[];
  budget: BudgetOut | undefined;
}

// The trip-overview page's one itinerary detail view (docs/18_phase6_app_shell_cursor_prompts.md
// Prompt 2) — LegTimeline's pill row was retired once TripRail took over as the
// permanent way to navigate between legs, so this carries everything the pills used
// to show (route, dates, state label, locked amount) in a single list instead of two.
export function ItineraryPanel({ legs, budget }: ItineraryPanelProps) {
  if (legs.length === 0) {
    return null;
  }

  const sortedLegs = [...legs].sort((a, b) => a.sequence_index - b.sequence_index);
  const budgetByLeg = new Map((budget?.by_leg ?? []).map((entry) => [entry.leg_id, entry]));
  const hasLockedOptions = (budget?.by_leg ?? []).some(
    (entry) => entry.locked_options.length > 0
  );
  const tripId = sortedLegs[0]?.trip_id;

  return (
    <section className="flex flex-col gap-3 rounded-panel border border-border-soft bg-bg p-6 shadow-card">
      <div className="flex items-baseline justify-between gap-4">
        <p className="mb-1 flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-[0.12em] text-ink-muted">
          <span className="size-1.5 rounded-full bg-coral-pink" />
          Itinerary
        </p>
        {hasLockedOptions && tripId && (
          <Link
            href={`/trips/${tripId}/budget`}
            className="text-sm text-turquoise underline underline-offset-2"
          >
            View full summary →
          </Link>
        )}
      </div>
      <ul className="flex flex-col gap-2">
        {sortedLegs.map((leg) => {
          const entry = budgetByLeg.get(leg.id);
          const state = derivePillState(leg, entry?.locked_option_ids ?? []);
          const isLocked = state === "locked";
          const amountLabel =
            isLocked && budget && entry?.amount
              ? formatCurrency(entry.amount, budget.home_currency)
              : "—";

          return (
            <li key={leg.id}>
              <Link
                href={`/trips/${leg.trip_id}/legs/${leg.id}`}
                className="flex items-center justify-between gap-4 rounded-card border border-border-soft bg-surface-alt px-4 py-3 transition-colors hover:text-turquoise"
              >
                <div className="flex flex-col gap-0.5">
                  <span
                    className={cn(
                      "text-sm",
                      isLocked ? "font-semibold text-deep-ocean" : "font-medium text-ink"
                    )}
                  >
                    {leg.origin} → {leg.destination}
                  </span>
                  <span className="text-xs text-ink-muted">
                    {formatDateShort(leg.start_date)} - {formatDateShort(leg.end_date)} ·{" "}
                    {PILL_LABEL[state]}
                  </span>
                </div>
                <span
                  className={cn(
                    "text-sm font-bold",
                    isLocked ? "text-deep-ocean" : "text-ink opacity-45"
                  )}
                >
                  {amountLabel}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

"use client";

import Link from "next/link";
import { useParams, usePathname } from "next/navigation";

import {
  derivePillState,
  PILL_LABEL,
  type PillState,
} from "@/components/shared/LegTimeline";
import { Skeleton } from "@/components/ui/skeleton";
import { useTrip, useTripBudget, useTripLegs } from "@/hooks/use-trips";
import type { LegOut } from "@/lib/types";
import { cn } from "@/lib/utils";

// Same PillState semantics as LegTimeline's PILL_FILL_CLASS, but a solid dot swatch
// rather than the big pill's tinted/shadowed fill (bg-destructive/10 at dot size would
// be nearly invisible, and text-color/shadow don't apply to an 8px circle with no text
// inside it — this is the dense-list-row treatment step 3c asks for, not the pill's).
// PILL_LABEL is still reused here, just as the dot's accessible name rather than
// always-visible row text — a color-only status indicator needs a text equivalent for
// screen readers/colorblind users regardless of whether it's also shown inline.
const PILL_DOT_CLASS: Record<PillState, string> = {
  not_started: "bg-ink-muted",
  researching: "bg-ink-muted",
  reviewing: "bg-coral-pink",
  locked: "bg-deep-ocean",
  failed: "bg-destructive",
};

type DayRow = {
  key: string;
  legId: string;
  date: Date;
  destination: string;
  travelFrom: string | null;
};

// Client-side day expansion for the left rail (docs/19_v2_scope_and_roadmap.md §1 /
// docs/20 Prompt 1). Not a materialized Day entity — just one row per calendar day
// derived from each leg's start_date + nights. 0-night pass-through legs still get
// exactly one row; travelFrom only on a leg's first day when origin differs from the
// previous leg's destination (leg 1 always shows it — previousDestination starts null).
function deriveDayRows(legs: LegOut[]): DayRow[] {
  const rows: DayRow[] = [];
  let previousDestination: string | null = null;

  for (const leg of legs) {
    const dayCount = Math.max(leg.nights, 1);
    // Calendar date in the browser's local zone (not UTC midnight) so formatting
    // below doesn't shift the day for users west of UTC.
    const [year, month, day] = leg.start_date.split("-").map(Number);
    const start = new Date(year, month - 1, day);

    for (let offset = 0; offset < dayCount; offset++) {
      const date = new Date(start);
      date.setDate(date.getDate() + offset);

      const showTravel =
        offset === 0 &&
        (previousDestination === null || leg.origin !== previousDestination);

      rows.push({
        key: `${leg.id}:${offset}`,
        legId: leg.id,
        date,
        destination: leg.destination,
        travelFrom: showTravel ? leg.origin : null,
      });
    }

    previousDestination = leg.destination;
  }

  return rows;
}

function formatDayDate(date: Date): string {
  return new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  }).format(date);
}

interface TripRailProps {
  tripId: string;
}

// Persistent left nav (docs/18_phase6_app_shell_cursor_prompts.md Prompt 1) — mounted
// once by app/(app)/trips/[tripId]/layout.tsx and kept alive across leg-to-leg
// navigation. Fetches via the same hooks/use-trips.ts query keys the pages below it
// use, so React Query dedupes rather than issuing a second round of requests.
export function TripRail({ tripId }: TripRailProps) {
  const pathname = usePathname();
  const { legId } = useParams<{ legId?: string }>();

  const tripQuery = useTrip(tripId);
  const legsQuery = useTripLegs(tripId);
  const budgetQuery = useTripBudget(tripId);

  const overviewHref = `/trips/${tripId}`;
  const budgetHref = `/trips/${tripId}/budget`;
  const isOverviewActive = pathname === overviewHref;
  const isBudgetActive = pathname === budgetHref;
  const hasLockedOptions = (budgetQuery.data?.by_leg ?? []).some(
    (entry) => entry.locked_options.length > 0
  );

  const sortedLegs = [...(legsQuery.data ?? [])].sort(
    (a, b) => a.sequence_index - b.sequence_index
  );
  const lockedOptionIdsByLeg = new Map(
    (budgetQuery.data?.by_leg ?? []).map((entry) => [entry.leg_id, entry.locked_option_ids])
  );
  const legById = new Map(sortedLegs.map((leg) => [leg.id, leg]));
  const dayRows = deriveDayRows(sortedLegs);

  return (
    <nav className="h-full w-72 shrink-0 overflow-y-auto border-r border-border-soft bg-surface-alt p-4">
      <Link
        href={overviewHref}
        className={cn(
          "block truncate rounded-pill px-3.5 py-2.5 text-sm",
          isOverviewActive ? "bg-bg font-bold text-ink" : "text-ink"
        )}
      >
        {tripQuery.data?.name ?? "Trip"}
      </Link>
      <Link
        href="/trips"
        className="mt-1 block px-3.5 py-1.5 text-xs text-ink-muted underline-offset-2 hover:text-turquoise hover:underline"
      >
        ← All trips
      </Link>
      {hasLockedOptions && (
        <Link
          href={budgetHref}
          className={cn(
            "mt-1 block truncate rounded-pill px-3.5 py-2 text-sm",
            isBudgetActive ? "bg-bg font-bold text-ink" : "text-ink-muted"
          )}
        >
          Locked summary
        </Link>
      )}

      <ul className="mt-2 flex flex-col gap-1">
        {legsQuery.isLoading ? (
          Array.from({ length: 3 }).map((_, index) => (
            <li key={index} className="px-3.5 py-2.5">
              <Skeleton className="h-9 w-full" />
            </li>
          ))
        ) : sortedLegs.length === 0 ? (
          <li className="px-3.5 py-2.5 text-sm text-ink-muted">
            No legs yet —{" "}
            <Link
              href={`/trips/${tripId}/wizard`}
              className="text-turquoise underline underline-offset-2"
            >
              add them in the wizard
            </Link>
            .
          </li>
        ) : (
          dayRows.map((row) => {
            const leg = legById.get(row.legId);
            if (!leg) {
              return null;
            }
            const isActive = leg.id === legId;
            const state = derivePillState(leg, lockedOptionIdsByLeg.get(leg.id) ?? []);
            return (
              <li key={row.key} className="min-w-0">
                <Link
                  href={`/trips/${tripId}/legs/${row.legId}`}
                  className={cn(
                    "flex min-w-0 flex-col gap-0.5 rounded-r-chip border-l-[3px] border-transparent px-3 py-2.5",
                    isActive ? "border-l-coral-pink bg-bg font-bold text-ink" : "text-ink"
                  )}
                >
                  {/* min-w-0 at each flex level: a flex item's default min-width is
                      "auto" (its content size), so without this the route text would
                      force the row wider instead of truncating — same gotcha as
                      AppShell's min-h-0, just the horizontal axis. */}
                  <span className="flex min-w-0 items-center gap-2">
                    <span
                      className={cn("size-2 shrink-0 rounded-full", PILL_DOT_CLASS[state])}
                      role="img"
                      aria-label={PILL_LABEL[state]}
                      title={PILL_LABEL[state]}
                    />
                    <span className="min-w-0 flex-1 truncate text-sm">
                      {formatDayDate(row.date)}
                    </span>
                  </span>
                  <span className="min-w-0 truncate pl-4 text-xs text-ink-muted">
                    {row.travelFrom
                      ? `${row.travelFrom} → ${row.destination}`
                      : row.destination}
                  </span>
                </Link>
              </li>
            );
          })
        )}
      </ul>
    </nav>
  );
}

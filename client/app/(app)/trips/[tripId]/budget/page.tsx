"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import {
  OPTION_TYPE_LABEL,
  OPTION_TYPE_ORDER,
} from "@/components/legs/CategoryTabs";
import { Skeleton } from "@/components/ui/skeleton";
import { useTrip, useTripBudget, useTripLegs } from "@/hooks/use-trips";
import { ApiError } from "@/lib/api-client";
import { formatCurrency } from "@/lib/format";
import {
  lockedLineTotalAmount,
  lockedPriceBreakdown,
  sectionUnitHeader,
} from "@/lib/locked-price";
import type {
  LockedOptionSummaryOut,
  OptionType,
} from "@/lib/types";

type SectionEntry = {
  legId: string;
  routeLabel: string;
  sequenceIndex: number;
  nights: number;
  option: LockedOptionSummaryOut;
};

function PriceColumns({
  breakdown,
}: {
  breakdown: NonNullable<ReturnType<typeof lockedPriceBreakdown>>;
}) {
  return (
    <div className="grid shrink-0 grid-cols-[minmax(5.5rem,auto)_minmax(4.5rem,auto)_minmax(5.5rem,auto)] items-baseline gap-x-3 text-right text-sm">
      <span className="font-medium text-ink">{breakdown.unit}</span>
      <span className="text-ink-muted">× {breakdown.qtyLabel}</span>
      <span className="font-bold text-ink">{breakdown.total}</span>
    </div>
  );
}

export default function TripBudgetPage() {
  const params = useParams<{ tripId: string }>();
  const tripId = params.tripId;

  const tripQuery = useTrip(tripId);
  const budgetQuery = useTripBudget(tripId);
  const legsQuery = useTripLegs(tripId);

  const isLoading =
    tripQuery.isLoading || budgetQuery.isLoading || legsQuery.isLoading;
  const error = tripQuery.error ?? budgetQuery.error ?? legsQuery.error;

  if (isLoading) {
    return (
      <div className="flex flex-col gap-4 p-6">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-3.5 w-full" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }

  if (error || !tripQuery.data || !budgetQuery.data) {
    const message =
      error instanceof ApiError ? error.message : "Could not load this budget.";
    return (
      <div className="flex flex-col gap-3 p-6">
        <p className="text-sm text-destructive">{message}</p>
        <Link href={`/trips/${tripId}`} className="text-sm text-turquoise underline">
          Back to trip
        </Link>
      </div>
    );
  }

  const trip = tripQuery.data;
  const budget = budgetQuery.data;
  const legsById = new Map((legsQuery.data ?? []).map((leg) => [leg.id, leg]));

  const targetAmount = budget.budget_target_amount;
  const target = targetAmount !== null ? Number(targetAmount) : null;

  const entriesByType = new Map<OptionType, SectionEntry[]>();
  for (const entry of budget.by_leg) {
    const leg = legsById.get(entry.leg_id);
    if (!leg) continue;
    for (const option of entry.locked_options) {
      const list = entriesByType.get(option.option_type) ?? [];
      list.push({
        legId: leg.id,
        routeLabel: `${leg.origin} → ${leg.destination}`,
        sequenceIndex: leg.sequence_index,
        nights: leg.nights,
        option,
      });
      entriesByType.set(option.option_type, list);
    }
  }

  const sections = OPTION_TYPE_ORDER.filter((type) => {
    const list = entriesByType.get(type);
    return list !== undefined && list.length > 0;
  }).map((type) => {
    const items = [...(entriesByType.get(type) ?? [])].sort(
      (a, b) => a.sequenceIndex - b.sequenceIndex
    );
    const subtotal = items.reduce(
      (sum, item) =>
        sum + lockedLineTotalAmount(item.option, { nights: item.nights }),
      0
    );
    return { type, items, subtotal };
  });

  const displayRunningTotal = sections.reduce(
    (sum, section) => sum + section.subtotal,
    0
  );
  const progressPct =
    target !== null && target > 0
      ? Math.min(100, Math.round((displayRunningTotal / target) * 100))
      : null;

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-8 p-6">
      <div className="flex flex-col gap-1">
        <p className="text-[12px] font-medium tracking-[0.12em] text-turquoise uppercase">
          Locked summary
        </p>
        <h1 className="font-display text-3xl font-bold tracking-tight text-ink md:text-4xl">
          {trip.name}
        </h1>
      </div>

      <section className="rounded-panel border border-border-soft p-6 shadow-card">
        {progressPct !== null && (
          <div className="mb-2.5 flex h-3.5 overflow-hidden rounded-pill bg-surface-alt">
            <div className="bg-coral-pink" style={{ width: `${progressPct}%` }} />
          </div>
        )}
        <div className="flex items-baseline justify-between text-sm">
          <span className="font-bold text-ink">
            {formatCurrency(String(displayRunningTotal), budget.home_currency)}{" "}
            locked
          </span>
          {targetAmount !== null && (
            <span className="text-ink-muted">
              of {formatCurrency(targetAmount, budget.home_currency)}
            </span>
          )}
        </div>
      </section>

      {sections.length === 0 ? (
        <p className="text-sm text-ink-muted">
          Nothing locked yet — lock options from each leg to build this summary.
        </p>
      ) : (
        sections.map(({ type, items, subtotal }) => {
          const unitHeader = sectionUnitHeader(type);
          const showColumns = unitHeader !== null;

          return (
            <section
              key={type}
              className="flex flex-col gap-3 rounded-panel border border-border-soft p-6 shadow-card"
            >
              <div className="flex items-baseline justify-between gap-4">
                <h2 className="font-display text-lg font-bold text-ink">
                  {OPTION_TYPE_LABEL[type]}
                </h2>
                <span className="text-sm font-bold text-ink">
                  {formatCurrency(String(subtotal), budget.home_currency)}
                </span>
              </div>

              {showColumns && (
                <div className="hidden grid-cols-[minmax(0,1fr)_minmax(5.5rem,auto)_minmax(4.5rem,auto)_minmax(5.5rem,auto)] gap-x-3 border-b border-border pb-2 text-[11px] font-bold tracking-[0.08em] text-ink-muted uppercase sm:grid">
                  <span>Option</span>
                  <span className="text-right">{unitHeader}</span>
                  <span className="text-right">×</span>
                  <span className="text-right">Total</span>
                </div>
              )}

              <ul className="flex flex-col divide-y divide-border">
                {items.map(({ legId, routeLabel, nights, option }) => {
                  const breakdown = lockedPriceBreakdown(option, { nights });
                  return (
                    <li
                      key={`${legId}:${option.option_card_id}`}
                      className="flex flex-col gap-2 py-3 sm:grid sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center sm:gap-4"
                    >
                      <div className="flex min-w-0 flex-col gap-0.5">
                        <span className="truncate text-sm font-medium text-ink">
                          {option.title}
                        </span>
                        <span className="text-xs text-ink-muted">{routeLabel}</span>
                        {option.room_label ? (
                          <span className="text-xs text-ink-muted">
                            {option.room_label}
                          </span>
                        ) : null}
                      </div>
                      {breakdown ? (
                        <PriceColumns breakdown={breakdown} />
                      ) : (
                        <span className="shrink-0 text-right text-sm font-bold text-ink">
                          {formatCurrency(option.amount, option.currency)}
                        </span>
                      )}
                    </li>
                  );
                })}
              </ul>
            </section>
          );
        })
      )}
    </div>
  );
}

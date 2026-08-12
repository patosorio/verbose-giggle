"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { toast } from "sonner";

import { AddManualOptionForm } from "@/components/legs/AddManualOptionForm";
import {
  CategoryTabs,
  OPTION_TYPE_LABEL,
  OPTION_TYPE_ORDER,
} from "@/components/legs/CategoryTabs";
import { OptionsTable } from "@/components/legs/OptionsTable";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { BudgetSidebar } from "@/components/trips/BudgetSidebar";
import { CrewCard } from "@/components/trips/CrewCard";
import { useLegOptions, useLockLeg, useUnlockLeg } from "@/hooks/use-legs";
import {
  useStartResearch,
  useTrip,
  useTripBudget,
  useTripLegs,
  useTripTravelers,
} from "@/hooks/use-trips";
import { ApiError } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";
import {
  isManualTabCategory,
  isUncategorizedImported,
  optionBelongsToTab,
  type ManualTabCategory,
} from "@/lib/manual-option-category";
import { occupancyPartySize } from "@/lib/occupancy";
import type { LegStatus, OptionType, ResearchRunType } from "@/lib/types";

const RESEARCH_RUN_TYPE_OPTIONS: { value: ResearchRunType; label: string }[] = [
  { value: "full", label: "Full" },
  { value: "flights", label: "Flights" },
  { value: "hotels", label: "Hotels" },
  { value: "activities", label: "Activities" },
  { value: "transport", label: "Transport" },
];

function emptyStateMessage(status: LegStatus | undefined, label: string): string {
  switch (status) {
    case "pending":
      return `Research hasn't started for ${label} yet.`;
    case "researching":
      return `Still researching ${label}…`;
    case "failed":
      return `Research failed for this leg — ${label} results may be incomplete.`;
    default:
      return `No ${label} found for this leg.`;
  }
}

export default function LegOptionsPage() {
  const params = useParams<{ tripId: string; legId: string }>();
  const { tripId, legId } = params;
  const { user } = useAuth();

  const budgetQuery = useTripBudget(tripId);
  const legsQuery = useTripLegs(tripId);
  const tripQuery = useTrip(tripId);
  const travelersQuery = useTripTravelers(tripId);

  const legForPolling = legsQuery.data?.find((l) => l.id === legId);
  const optionsQuery = useLegOptions(legId, {
    poll: legForPolling?.status === "researching",
  });

  const lockLeg = useLockLeg(tripId, legId);
  const unlockLeg = useUnlockLeg(tripId, legId);
  const startResearch = useStartResearch(tripId);

  const options = optionsQuery.data ?? [];

  const presentTypes = useMemo(() => {
    const found = new Set(options.map((o) => o.option_type));
    return OPTION_TYPE_ORDER.filter((type) => found.has(type));
  }, [options]);

  const hasUncategorizedImported = useMemo(
    () => options.some(isUncategorizedImported),
    [options]
  );

  const [activeType, setActiveType] = useState<OptionType>("hotel");
  const [selectedOptionId, setSelectedOptionId] = useState<string | null>(null);
  const [rerunType, setRerunType] = useState<ResearchRunType>("full");
  const [addManualOpen, setAddManualOpen] = useState(false);

  // Imported tab only appears for leftovers without a typed category_hint.
  useEffect(() => {
    if (activeType === "imported" && !hasUncategorizedImported) {
      setActiveType("hotel");
    }
  }, [activeType, hasUncategorizedImported]);

  // The page component persists across leg-to-leg navigation (same dynamic route),
  // so a "selected for locking" card from a previous leg must not carry over.
  useEffect(() => {
    setSelectedOptionId(null);
  }, [legId]);

  const isLoading =
    optionsQuery.isLoading ||
    budgetQuery.isLoading ||
    legsQuery.isLoading ||
    tripQuery.isLoading ||
    travelersQuery.isLoading;
  const error =
    optionsQuery.error ??
    budgetQuery.error ??
    legsQuery.error ??
    tripQuery.error ??
    travelersQuery.error;

  if (isLoading) {
    return (
      <div className="flex flex-col gap-4 p-6">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (error) {
    const message =
      error instanceof ApiError ? error.message : "Could not load options for this leg.";
    return (
      <div className="flex flex-col gap-3 p-6">
        <p className="text-sm text-destructive">{message}</p>
        <Link href={`/trips/${tripId}`} className="text-sm text-turquoise underline">
          Back to trip
        </Link>
      </div>
    );
  }

  const leg = legsQuery.data?.find((l) => l.id === legId);
  const trip = tripQuery.data;
  const budget = budgetQuery.data;

  if (!leg || !trip || !budget) {
    return (
      <div className="flex flex-col gap-3 p-6">
        <p className="text-sm text-destructive">This leg could not be found.</p>
        <Link href={`/trips/${tripId}`} className="text-sm text-turquoise underline">
          Back to trip
        </Link>
      </div>
    );
  }

  const filtered = options.filter((option) => optionBelongsToTab(option, activeType));
  const manualDefaultCategory: ManualTabCategory =
    isManualTabCategory(activeType) ? activeType : "hotel";
  const partySize = occupancyPartySize(leg.filters);
  const legBudget = budget.by_leg.find((entry) => entry.leg_id === legId);
  const lockedOptionIds = legBudget?.locked_option_ids ?? [];
  const bookedByOptionId: Record<string, boolean> = Object.fromEntries(
    (legBudget?.locked_options ?? []).map((option) => [
      option.option_card_id,
      option.is_booked,
    ])
  );
  const selectedIsLocked =
    selectedOptionId !== null && lockedOptionIds.includes(selectedOptionId);
  const isOrganizer = !!user && user.id === trip.organizer_id;

  function handleLock() {
    if (!selectedOptionId) return;
    lockLeg.mutate(selectedOptionId, {
      onSuccess: () => {
        toast.success("Option locked.");
        setSelectedOptionId(null);
      },
      onError: (err) => {
        toast.error(err instanceof ApiError ? err.message : "Could not lock this option.");
      },
    });
  }

  function handleUnlock() {
    if (!selectedOptionId) return;
    unlockLeg.mutate(selectedOptionId, {
      onSuccess: () => {
        toast.success("Option unlocked.");
        setSelectedOptionId(null);
      },
      onError: (err) => {
        toast.error(err instanceof ApiError ? err.message : "Could not unlock this option.");
      },
    });
  }

  function handleRerunResearch() {
    startResearch.mutate(
      { legId, run_type: rerunType },
      {
        onSuccess: () => {
          toast.success("Research started.");
        },
        onError: (err) => {
          toast.error(
            err instanceof ApiError ? err.message : "Could not start research."
          );
        },
      }
    );
  }

  const canStartResearch =
    isOrganizer &&
    (leg.status === "pending" || leg.status === "ready" || leg.status === "failed");
  const isFirstRun = leg.status === "pending";

  return (
    <div className="flex w-full flex-col gap-6 p-6 md:px-10">
      <div className="flex flex-col gap-8 md:flex-row md:items-start">
        <div className="flex min-w-0 flex-1 flex-col gap-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <CategoryTabs
              presentTypes={presentTypes}
              activeType={activeType}
              onChange={setActiveType}
              showImportedTab={hasUncategorizedImported}
            />
            <div className="flex flex-wrap items-center gap-2">
              {canStartResearch && (
                <>
                  <select
                    id="rerun-research-type"
                    aria-label={isFirstRun ? "Start research type" : "Re-run research type"}
                    className="h-8 rounded-pill border border-border-interactive bg-bg px-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                    value={rerunType}
                    onChange={(event) =>
                      setRerunType(event.target.value as ResearchRunType)
                    }
                  >
                    {RESEARCH_RUN_TYPE_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                  <Button
                    type="button"
                    size="sm"
                    disabled={startResearch.isPending}
                    onClick={handleRerunResearch}
                  >
                    {startResearch.isPending
                      ? "Starting…"
                      : isFirstRun
                        ? "Start research"
                        : "Re-run"}
                  </Button>
                </>
              )}
              <Dialog open={addManualOpen} onOpenChange={setAddManualOpen}>
                <DialogTrigger
                  render={<Button type="button" size="sm" variant="outline" />}
                >
                  + Add your own
                </DialogTrigger>
                <DialogContent>
                  <DialogTitle className="mb-4 font-heading text-lg font-bold text-ink">
                    Add your own option
                  </DialogTitle>
                  <AddManualOptionForm
                    legId={legId}
                    homeCurrency={trip.home_currency}
                    defaultCategory={manualDefaultCategory}
                    onSuccess={(category) => {
                      setAddManualOpen(false);
                      setActiveType(category);
                    }}
                  />
                </DialogContent>
              </Dialog>
            </div>
          </div>

          {filtered.length === 0 ? (
            <p className="text-sm text-ink-muted">
              {emptyStateMessage(leg.status, OPTION_TYPE_LABEL[activeType])}
            </p>
          ) : (
            <OptionsTable
              options={filtered}
              lockedOptionIds={lockedOptionIds}
              bookedByOptionId={bookedByOptionId}
              selectedOptionId={selectedOptionId}
              onSelectOption={setSelectedOptionId}
              nights={leg.nights}
              partySize={partySize}
            />
          )}

          {activeType === "activity" && filtered.length > 0 && (
            <div className="flex items-center gap-3.5 rounded-card bg-ink px-6 py-5 text-white">
              <span className="text-2xl" aria-hidden>
                ✦
              </span>
              <div>
                <p className="font-display text-[15px] font-bold">
                  Activities researched with citations
                </p>
                <p className="mt-0.5 text-sm text-white/70">
                  Every suggestion traces back to a real source.
                </p>
              </div>
            </div>
          )}
        </div>

        {/* sticky here, not on BudgetSidebar itself — it needs to carry CrewCard along
            with it so the two scroll as one unit instead of CrewCard sliding over the
            pinned BudgetSidebar on scroll-up. */}
        <div className="sticky top-6 flex w-full flex-col gap-5 md:w-80 md:shrink-0">
          <BudgetSidebar
            tripId={tripId}
            budget={budget}
            legs={legsQuery.data ?? []}
            currentLeg={leg}
            selectedIsLocked={selectedIsLocked}
            hasSelection={selectedOptionId !== null}
            isOrganizer={isOrganizer}
            isMutating={lockLeg.isPending || unlockLeg.isPending}
            onLock={handleLock}
            onUnlock={handleUnlock}
          />
          <CrewCard
            travelers={travelersQuery.data ?? []}
            organizerName={isOrganizer ? (user?.display_name ?? null) : null}
            isOrganizer={isOrganizer}
            tripId={tripId}
          />
        </div>
      </div>
    </div>
  );
}

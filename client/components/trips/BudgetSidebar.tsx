"use client";

import { useEffect, useState, type FormEvent } from "react";
import { toast } from "sonner";

import { OPTION_TYPE_LABEL } from "@/components/legs/CategoryTabs";
import { derivePillState } from "@/components/shared/LegTimeline";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAdjustLockPrice } from "@/hooks/use-legs";
import { ApiError } from "@/lib/api-client";
import { ACCENT_TEXT_CLASSES, accentAt } from "@/lib/constants";
import { formatCurrency } from "@/lib/format";
import { lockedLineTotalAmount, lockedPriceBreakdown } from "@/lib/locked-price";
import type { BudgetOut, LegOut, LockedOptionSummaryOut } from "@/lib/types";
import { cn } from "@/lib/utils";

function capitalize(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

interface BudgetSidebarProps {
  tripId: string;
  budget: BudgetOut;
  legs: LegOut[];
  currentLeg: LegOut;
  selectedIsLocked: boolean;
  hasSelection: boolean;
  isOrganizer: boolean;
  isMutating: boolean;
  onLock: () => void;
  onUnlock: () => void;
}

type EditingTarget = {
  legId: string;
  option: LockedOptionSummaryOut;
};

// Trip-level budget summary rendered on the leg options page (docs/07_design_spec.md §5):
// progress bar + full per-leg breakdown across the whole trip, but the Lock/Unlock CTA only
// ever acts on currentLeg — the leg the reviewer is actually looking at. Unlock is
// selection-scoped (the selected option_card_id) because a leg can carry multiple active
// locks after type-scoped uniqueness. The sticky positioning lives on the parent wrapper
// in legs/[legId]/page.tsx, not here — this card renders directly above CrewCard in that
// wrapper, and sticking only this div while CrewCard stayed normal-flow meant CrewCard
// (later in the DOM, so painted on top) slid over this card on scroll-up. Both cards now
// stick together as one unit instead.
export function BudgetSidebar({
  tripId,
  budget,
  legs,
  currentLeg,
  selectedIsLocked,
  hasSelection,
  isOrganizer,
  isMutating,
  onLock,
  onUnlock,
}: BudgetSidebarProps) {
  const [expandedLegIds, setExpandedLegIds] = useState<Set<string>>(new Set());
  const [editing, setEditing] = useState<EditingTarget | null>(null);
  const [priceAmount, setPriceAmount] = useState("");
  const [note, setNote] = useState("");
  const adjustPrice = useAdjustLockPrice(tripId);
  const sortedLegs = [...legs].sort((a, b) => a.sequence_index - b.sequence_index);
  const budgetByLeg = new Map(budget.by_leg.map((entry) => [entry.leg_id, entry]));
  const targetAmount = budget.budget_target_amount;
  const target = targetAmount !== null ? Number(targetAmount) : null;
  const displayRunningTotal = sortedLegs.reduce((sum, leg) => {
    const entry = budgetByLeg.get(leg.id);
    if (!entry) return sum;
    return (
      sum +
      entry.locked_options.reduce(
        (legSum, option) =>
          legSum + lockedLineTotalAmount(option, { nights: leg.nights }),
        0
      )
    );
  }, 0);
  const progressPct =
    target !== null && target > 0
      ? Math.min(100, Math.round((displayRunningTotal / target) * 100))
      : null;

  useEffect(() => {
    if (editing === null) return;
    setPriceAmount(editing.option.amount);
    setNote("");
  }, [editing]);

  function toggleExpanded(legId: string) {
    setExpandedLegIds((prev) => {
      const next = new Set(prev);
      if (next.has(legId)) {
        next.delete(legId);
      } else {
        next.add(legId);
      }
      return next;
    });
  }

  async function handleAdjustPrice(event: FormEvent) {
    event.preventDefault();
    if (editing === null) return;

    const trimmed = priceAmount.trim();
    const amount = Number(trimmed);
    if (trimmed === "" || Number.isNaN(amount)) {
      toast.error("Enter a valid price.");
      return;
    }

    const trimmedNote = note.trim();
    try {
      await adjustPrice.mutateAsync({
        legId: editing.legId,
        optionCardId: editing.option.option_card_id,
        body: {
          new_price_amount: amount,
          note: trimmedNote === "" ? null : trimmedNote,
        },
      });
      toast.success("Locked price updated.");
      setEditing(null);
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "Could not update locked price."
      );
    }
  }

  return (
    <div className="rounded-panel border border-border-soft p-6 shadow-card">
      <h2 className="font-display text-lg font-extrabold text-ink">Trip budget</h2>
      <p className="mb-4 text-sm text-ink-muted">
        {capitalize(budget.budget_band)} band · {budget.home_currency}
      </p>

      {progressPct !== null && (
        <div className="mb-2.5 flex h-3.5 overflow-hidden rounded-pill bg-surface-alt">
          <div className="bg-coral-pink" style={{ width: `${progressPct}%` }} />
        </div>
      )}
      <div className="mb-5 flex items-baseline justify-between text-sm">
        <span className="font-bold text-ink">
          {formatCurrency(String(displayRunningTotal), budget.home_currency)} locked
        </span>
        {targetAmount !== null && (
          <span className="text-ink-muted">
            of {formatCurrency(targetAmount, budget.home_currency)}
          </span>
        )}
      </div>

      <ul className="flex flex-col gap-3">
        {sortedLegs.map((leg, index) => {
          const entry = budgetByLeg.get(leg.id);
          const lockedOptions = entry?.locked_options ?? [];
          const isLegLocked = derivePillState(leg, entry?.locked_option_ids ?? []) === "locked";
          const accentClass = ACCENT_TEXT_CLASSES[accentAt(index)];
          const isExpanded = expandedLegIds.has(leg.id);
          const legTotal = lockedOptions.reduce(
            (sum, option) =>
              sum + lockedLineTotalAmount(option, { nights: leg.nights }),
            0
          );

          return (
            <li key={leg.id} className="flex flex-col gap-1.5">
              {isLegLocked ? (
                <button
                  type="button"
                  aria-expanded={isExpanded}
                  onClick={() => toggleExpanded(leg.id)}
                  className="flex w-full items-center justify-between gap-2 text-left text-sm"
                >
                  <span className={cn("flex min-w-0 items-center gap-1.5 font-semibold", accentClass)}>
                    <span className="shrink-0" aria-hidden>
                      {isExpanded ? "▾" : "▸"}
                    </span>
                    <span className="truncate">
                      {leg.origin} → {leg.destination}
                    </span>
                  </span>
                  <span className={cn("shrink-0 font-bold", accentClass)}>
                    {formatCurrency(String(legTotal), budget.home_currency)}
                  </span>
                </button>
              ) : (
                <div
                  className={cn(
                    "flex items-center justify-between text-sm opacity-45"
                  )}
                >
                  <span className="text-ink">
                    {leg.origin} → {leg.destination}
                  </span>
                  <span className="font-bold text-ink">—</span>
                </div>
              )}

              {isLegLocked && isExpanded && lockedOptions.length > 0 && (
                <ul className="flex flex-col gap-2 pl-5">
                  {lockedOptions.map((option) => {
                    const breakdown = lockedPriceBreakdown(option, {
                      nights: leg.nights,
                    });
                    return (
                      <li
                        key={option.option_card_id}
                        className="flex flex-col gap-0.5 text-sm text-ink-muted"
                      >
                        <div className="flex min-w-0 items-start justify-between gap-2">
                          <span className="min-w-0 truncate font-medium text-ink">
                            {option.title} · {OPTION_TYPE_LABEL[option.option_type]}
                          </span>
                          {isOrganizer ? (
                            <button
                              type="button"
                              onClick={() => setEditing({ legId: leg.id, option })}
                              className="shrink-0 text-xs font-semibold text-turquoise underline-offset-2 hover:underline"
                            >
                              Edit price
                            </button>
                          ) : null}
                        </div>
                        {option.room_label ? (
                          <span className="text-xs">{option.room_label}</span>
                        ) : null}
                        {breakdown ? (
                          <span className="text-xs">
                            {breakdown.unit} × {breakdown.qtyLabel} ={" "}
                            <span className="font-bold text-ink">{breakdown.total}</span>
                          </span>
                        ) : (
                          <span className="font-bold text-ink">
                            {formatCurrency(option.amount, option.currency)}
                          </span>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
            </li>
          );
        })}
      </ul>

      {!isOrganizer ? (
        <p className="mt-5 text-center text-xs text-ink-muted">
          Only the trip organizer can lock options.
        </p>
      ) : selectedIsLocked ? (
        <button
          type="button"
          onClick={onUnlock}
          disabled={isMutating}
          className="mt-5 w-full rounded-pill bg-surface-alt py-3.5 font-display text-sm font-bold text-ink transition-opacity disabled:opacity-60"
        >
          {isMutating ? "Unlocking…" : `Unlock ${currentLeg.destination} option`}
        </button>
      ) : (
        <button
          type="button"
          onClick={onLock}
          disabled={isMutating || !hasSelection}
          className="mt-5 w-full rounded-pill bg-sunshine py-3.5 font-display text-sm font-bold text-ink transition-opacity disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isMutating
            ? "Locking…"
            : hasSelection
              ? `Lock ${currentLeg.destination} option`
              : "Select an option to lock"}
        </button>
      )}

      <Dialog
        open={editing !== null}
        onOpenChange={(open) => {
          if (!open) setEditing(null);
        }}
      >
        <DialogContent>
          <DialogTitle className="mb-4 font-display text-lg font-bold text-ink">
            Edit locked price
          </DialogTitle>
          {editing ? (
            <form onSubmit={handleAdjustPrice} className="flex flex-col gap-4">
              <p className="text-sm text-ink-muted">
                {editing.option.title} ·{" "}
                {OPTION_TYPE_LABEL[editing.option.option_type]} ·{" "}
                {budget.home_currency}
              </p>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="locked-price-amount">New price</Label>
                <Input
                  id="locked-price-amount"
                  type="number"
                  inputMode="decimal"
                  step="0.01"
                  min="0"
                  value={priceAmount}
                  onChange={(event) => setPriceAmount(event.target.value)}
                  required
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="locked-price-note">Note (optional)</Label>
                <Input
                  id="locked-price-note"
                  type="text"
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  placeholder="e.g. phone discount"
                />
              </div>
              <div className="flex justify-end gap-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setEditing(null)}
                  disabled={adjustPrice.isPending}
                >
                  Cancel
                </Button>
                <Button type="submit" disabled={adjustPrice.isPending}>
                  {adjustPrice.isPending ? "Saving…" : "Save price"}
                </Button>
              </div>
            </form>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}

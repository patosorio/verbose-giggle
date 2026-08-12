"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { Button, buttonVariants } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useDeleteTrip, usePatchTrip } from "@/hooks/use-trips";
import { ApiError } from "@/lib/api-client";
import { ACCENT_TEXT_CLASSES, accentAt } from "@/lib/constants";
import { formatPartySize } from "@/lib/format";
import type { BudgetBand, LegOut, TravelerOut, TripOut, TripStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const sunshineActionClassName =
  "border border-border-interactive bg-sunshine text-ink hover:bg-sunshine hover:brightness-[1.05] hover:text-ink";

function statusEyebrow(status: TripStatus): string {
  switch (status) {
    case "planning":
      return "Trip in planning";
    case "locked":
      return "Trip locked";
    case "completed":
      return "Trip completed";
    case "archived":
      return "Trip archived";
  }
}

function formatBand(band: BudgetBand): string {
  return band.charAt(0).toUpperCase() + band.slice(1);
}

// The mockup collapses adjacent legs' shared endpoint (e.g. Phuket appears once,
// not as both leg 1's destination and leg 2's origin) rather than concatenating
// every leg's own origin+destination independently.
function buildStopSequence(legs: LegOut[]): string[] {
  const stops: string[] = [];
  legs.forEach((leg, index) => {
    if (index === 0 || stops[stops.length - 1] !== leg.origin) {
      stops.push(leg.origin);
    }
    stops.push(leg.destination);
  });
  return stops;
}

interface TripHeaderProps {
  trip: TripOut;
  legs: LegOut[];
  travelers: TravelerOut[];
  isOrganizer: boolean;
  /** When set, Edit / Remove / Add-legs render as one sunshine action cluster. */
  addLegsHref?: string;
  addLegsLabel?: string;
}

export function TripHeader({
  trip,
  legs,
  travelers,
  isOrganizer,
  addLegsHref,
  addLegsLabel,
}: TripHeaderProps) {
  const router = useRouter();
  const sortedLegs = [...legs].sort((a, b) => a.sequence_index - b.sequence_index);
  const stops = buildStopSequence(sortedLegs);

  const patchTrip = usePatchTrip(trip.id);
  const deleteTrip = useDeleteTrip();

  const [editOpen, setEditOpen] = useState(false);
  const [name, setName] = useState(trip.name);
  const [budgetBand, setBudgetBand] = useState<BudgetBand>(trip.budget_band);
  const [budgetTarget, setBudgetTarget] = useState(
    trip.budget_target_amount ?? ""
  );

  async function handleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedTarget = budgetTarget.trim();
    const target = trimmedTarget === "" ? null : Number(trimmedTarget);
    if (target !== null && Number.isNaN(target)) {
      toast.error("Budget target must be a number.");
      return;
    }
    try {
      await patchTrip.mutateAsync({
        name: name.trim(),
        budget_band: budgetBand,
        budget_target_amount: target,
      });
      toast.success("Trip updated.");
      setEditOpen(false);
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "Could not update this trip."
      );
    }
  }

  async function handleDelete() {
    const confirmed = window.confirm(
      `Remove “${trip.name}”? It will leave your trip list (archived).`
    );
    if (!confirmed) return;
    try {
      await deleteTrip.mutateAsync(trip.id);
      toast.success("Trip removed.");
      router.push("/trips");
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "Could not remove this trip."
      );
    }
  }

  const showActions = isOrganizer && trip.status !== "archived";

  return (
    <header className="flex flex-col gap-4">
      <p className="text-[12px] font-medium tracking-[0.12em] text-turquoise uppercase">
        {statusEyebrow(trip.status)} · {formatBand(trip.budget_band)} tier
      </p>

      <h1 className="font-display text-4xl font-bold tracking-tight text-ink md:text-5xl">
        {trip.name}
      </h1>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
        <p className="text-sm text-ink-muted">{formatPartySize(travelers)}</p>

        {stops.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 rounded-panel bg-surface-alt px-[22px] py-4 text-base">
            {stops.map((stop, index) => (
              <span key={index} className="flex items-center gap-2">
                {index > 0 && (
                  <span
                    className={cn("font-bold", ACCENT_TEXT_CLASSES[accentAt(index - 1)])}
                    aria-hidden
                  >
                    →
                  </span>
                )}
                <span className="font-bold text-ink">{stop}</span>
              </span>
            ))}
          </div>
        )}

        {showActions && (
          <div className="flex flex-wrap items-center gap-2">
            <Dialog
              open={editOpen}
              onOpenChange={(open) => {
                if (open) {
                  setName(trip.name);
                  setBudgetBand(trip.budget_band);
                  setBudgetTarget(trip.budget_target_amount ?? "");
                }
                setEditOpen(open);
              }}
            >
              <DialogTrigger
                render={
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className={sunshineActionClassName}
                  />
                }
              >
                Edit trip
              </DialogTrigger>
              <DialogContent>
                <DialogTitle className="mb-4 font-display text-lg font-bold text-ink">
                  Edit trip
                </DialogTitle>
                <form onSubmit={handleSave} className="flex flex-col gap-3">
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="edit-trip-name">Name</Label>
                    <Input
                      id="edit-trip-name"
                      required
                      value={name}
                      onChange={(event) => setName(event.target.value)}
                    />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="edit-trip-band">Budget band</Label>
                    <select
                      id="edit-trip-band"
                      className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                      value={budgetBand}
                      onChange={(event) =>
                        setBudgetBand(event.target.value as BudgetBand)
                      }
                    >
                      <option value="budget">Budget</option>
                      <option value="comfort">Comfort</option>
                      <option value="premium">Premium</option>
                    </select>
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="edit-trip-target">
                      Budget target ({trip.home_currency})
                    </Label>
                    <Input
                      id="edit-trip-target"
                      type="number"
                      min={0}
                      step="1"
                      placeholder="Optional"
                      value={budgetTarget}
                      onChange={(event) => setBudgetTarget(event.target.value)}
                    />
                  </div>
                  <Button type="submit" disabled={patchTrip.isPending}>
                    {patchTrip.isPending ? "Saving…" : "Save"}
                  </Button>
                </form>
              </DialogContent>
            </Dialog>

            <Button
              type="button"
              variant="outline"
              size="sm"
              className={sunshineActionClassName}
              disabled={deleteTrip.isPending}
              onClick={handleDelete}
            >
              {deleteTrip.isPending ? "Removing…" : "Remove trip"}
            </Button>

            {addLegsHref && addLegsLabel && (
              <Link
                href={addLegsHref}
                className={cn(
                  buttonVariants({ variant: "outline", size: "sm" }),
                  sunshineActionClassName
                )}
              >
                {addLegsLabel}
              </Link>
            )}
          </div>
        )}
      </div>
    </header>
  );
}

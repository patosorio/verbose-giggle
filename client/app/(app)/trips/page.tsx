"use client";

import Link from "next/link";
import { toast } from "sonner";

import { Button, buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/lib/auth-context";
import { useDeleteTrip, useTrips } from "@/hooks/use-trips";
import { ApiError } from "@/lib/api-client";
import type { BudgetBand, TripStatus } from "@/lib/types";

function formatBudgetBand(band: BudgetBand): string {
  return band.charAt(0).toUpperCase() + band.slice(1);
}

function formatStatus(status: TripStatus): string {
  return status.charAt(0).toUpperCase() + status.slice(1);
}

export default function TripsPage() {
  const { user } = useAuth();
  const { data: trips, isLoading, isError, error } = useTrips();
  const deleteTrip = useDeleteTrip();

  async function handleDelete(tripId: string, tripName: string) {
    const confirmed = window.confirm(
      `Remove “${tripName}”? It will leave your trip list (archived).`
    );
    if (!confirmed) return;
    try {
      await deleteTrip.mutateAsync(tripId);
      toast.success("Trip removed.");
    } catch (err) {
      toast.error(
        err instanceof ApiError ? err.message : "Could not remove this trip."
      );
    }
  }

  if (isLoading) {
    return (
      <div className="flex flex-col gap-4 p-6">
        <Skeleton className="h-10 w-48" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }

  if (isError) {
    const message =
      error instanceof ApiError ? error.message : "Could not load trips.";
    return (
      <div className="p-6">
        <p className="text-sm text-destructive">{message}</p>
      </div>
    );
  }

  const list = trips ?? [];

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 p-6">
      <div className="flex items-center justify-between gap-4">
        <h1 className="font-display text-2xl font-bold text-ink">Trips</h1>
        <Link href="/trips/new" className={buttonVariants({ variant: "default" })}>
          New trip
        </Link>
      </div>

      {list.length === 0 ? (
        <p className="text-sm text-ink-muted">
          No trips yet. Create one to get started.
        </p>
      ) : (
        <ul className="flex flex-col gap-3">
          {list.map((trip) => {
            // Prefer organizer_id gate; if an older API omits it, still show Remove —
            // DELETE is require_organizer and will 403 for non-organizers.
            const canRemove =
              !!user &&
              (trip.organizer_id == null || user.id === trip.organizer_id);
            return (
              <li key={trip.id}>
                <div className="flex items-center gap-2 rounded-card border border-border-soft bg-bg px-4 py-3 shadow-card">
                  <Link
                    href={`/trips/${trip.id}`}
                    className="flex min-w-0 flex-1 items-center justify-between gap-4 transition-colors hover:text-turquoise"
                  >
                    <div className="min-w-0">
                      <p className="truncate font-heading text-base font-medium text-ink">
                        {trip.name}
                      </p>
                      <p className="mt-0.5 text-sm text-ink-muted">
                        {formatBudgetBand(trip.budget_band)} ·{" "}
                        {formatStatus(trip.status)}
                      </p>
                    </div>
                    <span className="shrink-0 text-sm text-turquoise">Open →</span>
                  </Link>
                  {canRemove && (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="shrink-0 border-destructive/40 text-destructive hover:bg-destructive/10 hover:text-destructive"
                      disabled={deleteTrip.isPending}
                      onClick={() => handleDelete(trip.id, trip.name)}
                    >
                      Remove
                    </Button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

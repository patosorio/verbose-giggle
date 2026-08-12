"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { ItineraryPanel } from "@/components/shared/ItineraryPanel";
import { TripHeader } from "@/components/shared/TripHeader";
import { CrewCard } from "@/components/trips/CrewCard";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useTrip,
  useTripBudget,
  useTripLegs,
  useTripTravelers,
} from "@/hooks/use-trips";
import { ApiError } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";

export default function TripPage() {
  const params = useParams<{ tripId: string }>();
  const tripId = params.tripId;
  const { user } = useAuth();

  const tripQuery = useTrip(tripId);
  const travelersQuery = useTripTravelers(tripId);
  const legsQuery = useTripLegs(tripId);
  const budgetQuery = useTripBudget(tripId);

  const isLoading =
    tripQuery.isLoading ||
    travelersQuery.isLoading ||
    legsQuery.isLoading ||
    budgetQuery.isLoading;

  const error =
    tripQuery.error ?? travelersQuery.error ?? legsQuery.error ?? budgetQuery.error;

  if (isLoading) {
    return (
      <div className="flex flex-col gap-4 p-6">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-14 w-2/3" />
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-16 w-full" />
      </div>
    );
  }

  if (error || !tripQuery.data) {
    const message =
      error instanceof ApiError
        ? error.message
        : "Could not load this trip.";
    return (
      <div className="flex flex-col gap-3 p-6">
        <p className="text-sm text-destructive">{message}</p>
        <Link href="/trips" className="text-sm text-turquoise underline">
          Back to trips
        </Link>
      </div>
    );
  }

  const trip = tripQuery.data;
  const legs = legsQuery.data ?? [];
  const travelers = travelersQuery.data ?? [];
  const isOrganizer = !!user && user.id === trip.organizer_id;

  return (
    <div className="flex w-full flex-col gap-8 p-6 md:px-10">
      <TripHeader
        trip={trip}
        legs={legs}
        travelers={travelers}
        isOrganizer={isOrganizer}
        addLegsHref={`/trips/${tripId}/wizard`}
        addLegsLabel={legs.length === 0 ? "Add legs in wizard" : "Add more legs"}
      />

      {/* Main column stretches to the rail; turquoise CrewCard is its own right column. */}
      <div className="flex flex-col gap-8 md:flex-row md:items-start">
        <div className="flex min-w-0 flex-1 flex-col gap-6">
          {legs.length === 0 ? (
            <section className="flex flex-col gap-3 rounded-panel border border-border-soft p-6 shadow-card">
              <h2 className="font-display text-lg font-bold text-ink">Itinerary</h2>
              <p className="text-sm text-ink-muted">
                No legs yet — use the wizard to add routes and start research.
              </p>
            </section>
          ) : (
            <ItineraryPanel legs={legs} budget={budgetQuery.data} />
          )}
        </div>

        <div className="w-full md:w-80 md:shrink-0">
          <CrewCard
            travelers={travelers}
            organizerName={isOrganizer ? (user?.display_name ?? null) : null}
            isOrganizer={isOrganizer}
            tripId={tripId}
          />
        </div>
      </div>
    </div>
  );
}

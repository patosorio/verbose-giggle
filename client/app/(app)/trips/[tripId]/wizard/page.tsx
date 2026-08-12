"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";

import { RouteDatesForm } from "@/components/wizard/RouteDatesForm";
import { SearchSetupStep } from "@/components/wizard/SearchSetupStep";
import { Skeleton } from "@/components/ui/skeleton";
import { buttonVariants } from "@/components/ui/button";
import { useTrip, useTripLegs } from "@/hooks/use-trips";
import { ApiError } from "@/lib/api-client";
import type { LegOut } from "@/lib/types";
import { cn } from "@/lib/utils";

export default function TripWizardPage() {
  const { tripId } = useParams<{ tripId: string }>();
  const router = useRouter();

  const [step, setStep] = useState<"route" | "search-setup">("route");
  const [createdLegs, setCreatedLegs] = useState<LegOut[] | null>(null);

  const tripQuery = useTrip(tripId);
  const legsQuery = useTripLegs(tripId);

  const isLoading = tripQuery.isLoading || legsQuery.isLoading;
  const error = tripQuery.error ?? legsQuery.error;

  if (isLoading) {
    return (
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-4 p-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (error || !tripQuery.data) {
    const message =
      error instanceof ApiError ? error.message : "Could not load this trip.";
    return (
      <div className="flex flex-col gap-3 p-6">
        <p className="text-sm text-destructive">{message}</p>
        <Link href="/trips" className="text-sm text-turquoise underline">
          Back to trips
        </Link>
      </div>
    );
  }

  const existingLegs = legsQuery.data ?? [];
  const nextSequenceIndex =
    existingLegs.length === 0
      ? 0
      : Math.max(...existingLegs.map((leg) => leg.sequence_index)) + 1;

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 p-6">
      <div className="flex flex-col gap-2">
        <Link
          href={`/trips/${tripId}`}
          className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "w-fit px-0")}
        >
          ← Back to trip
        </Link>
        <p className="text-xs font-bold tracking-[0.14em] text-ink-muted uppercase">
          {step === "route" ? "Step 1 of 2" : "Step 2 of 2"}
        </p>
        <h1 className="font-display text-2xl font-bold text-ink">
          {step === "route" ? "Add legs" : "Party & filters"}
        </h1>
        <p className="text-sm text-ink-muted">
          {step === "route"
            ? "Set the route and dates for each stop. Research starts on the next step."
            : "Confirm who's going and optional flight/hotel filters, then start research."}
        </p>
      </div>

      {step === "route" ? (
        <RouteDatesForm
          tripId={tripId}
          nextSequenceIndex={nextSequenceIndex}
          onCreated={(legs) => {
            setCreatedLegs(legs);
            setStep("search-setup");
          }}
        />
      ) : (
        createdLegs && (
          <SearchSetupStep
            tripId={tripId}
            homeCurrency={tripQuery.data.home_currency}
            legs={createdLegs}
            onComplete={() => router.push(`/trips/${tripId}`)}
          />
        )
      )}
    </div>
  );
}

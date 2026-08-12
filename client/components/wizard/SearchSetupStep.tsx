"use client";

import { useFieldArray, useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";

import {
  DEFAULT_LEG_FILTERS,
  LegFiltersFields,
  legFiltersFieldsSchema,
} from "@/components/legs/LegFiltersFields";
import { formatDateShort } from "@/components/shared/ItineraryPanel";
import { Button } from "@/components/ui/button";
import { usePatchLeg } from "@/hooks/use-legs";
import { useStartResearch } from "@/hooks/use-trips";
import type { LegCreateIn, LegOut, LegPatchIn } from "@/lib/types";

const legFiltersSchema = legFiltersFieldsSchema.extend({
  legId: z.string().uuid(),
});

const formSchema = z.object({
  legs: z.array(legFiltersSchema).min(1),
});

type FormValues = z.infer<typeof formSchema>;

function buildFilters(leg: FormValues["legs"][number]): LegCreateIn["filters"] | undefined {
  const flight: NonNullable<LegCreateIn["filters"]>["flight"] = {};
  if (leg.max_stops !== undefined) {
    flight.max_stops = leg.max_stops;
  }
  if (leg.max_price !== undefined) {
    flight.max_price = leg.max_price;
  }

  const hotel: NonNullable<LegCreateIn["filters"]>["hotel"] = {};
  if (leg.star_class.length > 0) {
    hotel.star_class = leg.star_class;
  }
  if (leg.free_cancellation_only) {
    hotel.free_cancellation_only = true;
  }
  if (leg.hotel_price_min !== undefined && leg.hotel_price_max !== undefined) {
    hotel.price_range = {
      min: leg.hotel_price_min,
      max: leg.hotel_price_max,
    };
  }

  const filters: NonNullable<LegCreateIn["filters"]> = {
    occupancy: {
      rooms: leg.rooms.map((room) => ({
        adults: room.adults,
        children: room.children,
        children_ages: room.children_ages.slice(0, room.children),
      })),
    },
  };
  if (Object.keys(flight).length > 0) {
    filters.flight = flight;
  }
  if (Object.keys(hotel).length > 0) {
    filters.hotel = hotel;
  }
  return filters;
}

interface SearchSetupStepProps {
  tripId: string;
  homeCurrency: string;
  legs: LegOut[];
  onComplete: () => void;
}

export function SearchSetupStep({
  tripId,
  homeCurrency,
  legs,
  onComplete,
}: SearchSetupStepProps) {
  const patchLeg = usePatchLeg(tripId);
  const startResearch = useStartResearch(tripId);

  const {
    register,
    control,
    handleSubmit,
    watch,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      legs: legs.map((leg) => ({
        legId: leg.id,
        ...DEFAULT_LEG_FILTERS,
        rooms: [{ ...DEFAULT_LEG_FILTERS.rooms[0], children_ages: [] }],
        skip_hotel: leg.skip_hotel ?? false,
        skip_flight: leg.skip_flight ?? false,
      })),
    },
  });

  const { fields } = useFieldArray({ control, name: "legs" });

  async function onSubmit(values: FormValues) {
    // Sequential per leg (patch then research) so a failure attributes cleanly;
    // wrap each sequence in allSettled so one rejection doesn't abort the rest.
    const results: PromiseSettledResult<void>[] = [];
    for (const row of values.legs) {
      const [settled] = await Promise.allSettled([
        (async () => {
          const filters = buildFilters(row);
          const body: LegPatchIn = {
            skip_hotel: row.skip_hotel,
            skip_flight: row.skip_flight,
          };
          if (filters !== undefined) {
            body.filters = filters;
          }
          await patchLeg.mutateAsync({ legId: row.legId, body });
          await startResearch.mutateAsync({ legId: row.legId, run_type: "full" });
        })(),
      ]);
      results.push(settled);
    }

    const failedCount = results.filter((r) => r.status === "rejected").length;
    const base = legs.length === 1 ? "Leg added." : `${legs.length} legs added.`;
    toast.success(
      failedCount > 0
        ? `${base} — research couldn't start for ${failedCount} of them, retry from the leg page`
        : base
    );
    onComplete();
  }

  const isBusy =
    isSubmitting || patchLeg.isPending || startResearch.isPending;

  return (
    <div className="flex flex-col gap-8">
      <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-6">
        <section className="flex flex-col gap-4">
          <h2 className="text-xs font-bold tracking-[0.14em] text-ink uppercase">
            Search filters
          </h2>

          <ul className="flex flex-col gap-4">
            {fields.map((field, index) => {
              const leg = legs[index];
              if (!leg) return null;

              return (
                <li
                  key={field.id}
                  className="flex flex-col gap-4 rounded-card border border-border-soft bg-bg p-4 shadow-card"
                >
                  <input type="hidden" {...register(`legs.${index}.legId`)} />
                  <div className="flex flex-col gap-0.5">
                    <h3 className="font-display text-base font-bold text-ink">
                      {leg.origin} → {leg.destination}
                    </h3>
                    <p className="text-sm text-ink-muted">
                      {formatDateShort(leg.start_date)} – {formatDateShort(leg.end_date)}
                    </p>
                  </div>

                  <LegFiltersFields
                    legIndex={index}
                    homeCurrency={homeCurrency}
                    control={control}
                    register={register}
                    setValue={setValue}
                    watch={watch}
                    errors={errors.legs?.[index]}
                  />
                </li>
              );
            })}
          </ul>
        </section>

        <Button type="submit" disabled={isBusy} className="w-full sm:w-auto">
          {isBusy ? "Starting…" : "Start research"}
        </Button>
      </form>
    </div>
  );
}

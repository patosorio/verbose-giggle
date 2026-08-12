"use client";

import { useFieldArray, useForm, type Control, type FieldErrors, type UseFormRegister, type UseFormSetValue, type UseFormWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";

import { formatDateShort } from "@/components/shared/ItineraryPanel";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { usePatchLeg } from "@/hooks/use-legs";
import { useStartResearch } from "@/hooks/use-trips";
import type { LegCreateIn, LegOut, LegPatchIn } from "@/lib/types";

const optionalNumber = z.preprocess((value) => {
  if (value === "" || value === null || value === undefined) return undefined;
  if (typeof value === "number" && Number.isNaN(value)) return undefined;
  return value;
}, z.number().nonnegative().optional());

const roomSchema = z
  .object({
    adults: z.coerce.number().int().min(1).max(6),
    children: z.coerce.number().int().min(0).max(5),
    children_ages: z.array(z.coerce.number().int().min(0).max(17)).default([]),
  })
  .superRefine((room, ctx) => {
    if (room.adults + room.children > 6) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "At most 6 travelers per room (adults + children)",
        path: ["adults"],
      });
    }
    if (room.children_ages.length !== room.children) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Set an age (0–17) for each child",
        path: ["children_ages"],
      });
    }
  });

const legFiltersSchema = z.object({
  legId: z.string().uuid(),
  rooms: z.array(roomSchema).min(1).max(20),
  max_stops: z.preprocess((value) => {
    if (value === "" || value === null || value === undefined) return undefined;
    return value;
  }, z.number().int().min(0).max(1).optional()),
  max_price: optionalNumber,
  skip_hotel: z.boolean().default(false),
  star_class: z.array(z.coerce.number().int().min(1).max(5)).default([]),
  free_cancellation_only: z.boolean().default(false),
  hotel_price_min: optionalNumber,
  hotel_price_max: optionalNumber,
});

const formSchema = z.object({
  legs: z.array(legFiltersSchema).min(1),
});

type FormValues = z.infer<typeof formSchema>;

const selectClassName =
  "h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50";

const DEFAULT_ROOM = { adults: 2, children: 0, children_ages: [] as number[] };

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

interface LegRoomsFieldsProps {
  legIndex: number;
  control: Control<FormValues>;
  register: UseFormRegister<FormValues>;
  setValue: UseFormSetValue<FormValues>;
  watch: UseFormWatch<FormValues>;
  errors: FieldErrors<FormValues["legs"][number]> | undefined;
}

function LegRoomsFields({
  legIndex,
  control,
  register,
  setValue,
  watch,
  errors,
}: LegRoomsFieldsProps) {
  const { fields, append, remove } = useFieldArray({
    control,
    name: `legs.${legIndex}.rooms`,
  });
  const rooms = watch(`legs.${legIndex}.rooms`) ?? [];
  const totalAdults = rooms.reduce((sum, room) => sum + (Number(room?.adults) || 0), 0);
  const totalChildren = rooms.reduce(
    (sum, room) => sum + (Number(room?.children) || 0),
    0
  );

  function syncChildrenAges(roomIndex: number, nextChildren: number) {
    const current = watch(`legs.${legIndex}.rooms.${roomIndex}.children_ages`) ?? [];
    const nextAges = Array.from({ length: nextChildren }, (_, i) =>
      current[i] !== undefined && current[i] !== null ? Number(current[i]) : 0
    );
    setValue(`legs.${legIndex}.rooms.${roomIndex}.children_ages`, nextAges, {
      shouldValidate: true,
    });
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs font-bold tracking-[0.14em] text-ink-muted uppercase">
        Guests &amp; rooms
      </p>
      <ul className="flex flex-col gap-3">
        {fields.map((field, roomIndex) => {
          const room = rooms[roomIndex];
          const adults = Number(room?.adults) || 0;
          const children = Number(room?.children) || 0;
          const overCap = adults + children > 6;
          const roomError = errors?.rooms?.[roomIndex];

          const childrenRegister = register(
            `legs.${legIndex}.rooms.${roomIndex}.children`,
            {
              setValueAs: (value) => {
                const n = Number(value);
                return Number.isFinite(n) ? n : 0;
              },
            }
          );

          return (
            <li
              key={field.id}
              className="flex flex-col gap-2 rounded-[12px] border border-border-soft bg-surface-alt p-3 shadow-card"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium text-ink">Room {roomIndex + 1}</span>
                {fields.length > 1 ? (
                  <button
                    type="button"
                    className="text-sm text-ink-muted underline-offset-2 hover:text-ink hover:underline"
                    onClick={() => remove(roomIndex)}
                  >
                    Remove
                  </button>
                ) : null}
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor={`legs.${legIndex}.rooms.${roomIndex}.adults`}>
                    Adults
                  </Label>
                  <Input
                    id={`legs.${legIndex}.rooms.${roomIndex}.adults`}
                    type="number"
                    min={1}
                    max={6}
                    {...register(`legs.${legIndex}.rooms.${roomIndex}.adults`, {
                      setValueAs: (value) => {
                        const n = Number(value);
                        return Number.isFinite(n) ? n : 1;
                      },
                    })}
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor={`legs.${legIndex}.rooms.${roomIndex}.children`}>
                    Children
                  </Label>
                  <Input
                    id={`legs.${legIndex}.rooms.${roomIndex}.children`}
                    type="number"
                    min={0}
                    max={5}
                    name={childrenRegister.name}
                    ref={childrenRegister.ref}
                    onBlur={childrenRegister.onBlur}
                    onChange={(event) => {
                      void childrenRegister.onChange(event);
                      const n = Number(event.target.value);
                      syncChildrenAges(roomIndex, Number.isFinite(n) ? n : 0);
                    }}
                  />
                </div>
              </div>
              {children > 0 ? (
                <div className="flex flex-col gap-1.5">
                  <span className="text-sm font-medium text-ink">Child ages</span>
                  <div className="flex flex-wrap gap-2">
                    {Array.from({ length: children }, (_, ageIndex) => (
                      <div
                        key={ageIndex}
                        className="flex flex-col gap-1"
                      >
                        <Label
                          htmlFor={`legs.${legIndex}.rooms.${roomIndex}.children_ages.${ageIndex}`}
                          className="text-xs text-ink-muted"
                        >
                          Child {ageIndex + 1}
                        </Label>
                        <Input
                          id={`legs.${legIndex}.rooms.${roomIndex}.children_ages.${ageIndex}`}
                          type="number"
                          min={0}
                          max={17}
                          className="w-20"
                          {...register(
                            `legs.${legIndex}.rooms.${roomIndex}.children_ages.${ageIndex}`,
                            {
                              setValueAs: (value) => {
                                const n = Number(value);
                                return Number.isFinite(n) ? n : 0;
                              },
                            }
                          )}
                        />
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
              {overCap || roomError?.adults?.message ? (
                <p className="text-sm text-destructive">
                  {typeof roomError?.adults?.message === "string"
                    ? roomError.adults.message
                    : "At most 6 travelers per room (adults + children)"}
                </p>
              ) : null}
              {typeof roomError?.children_ages?.message === "string" ? (
                <p className="text-sm text-destructive">
                  {roomError.children_ages.message}
                </p>
              ) : null}
            </li>
          );
        })}
      </ul>
      {fields.length < 20 ? (
        <button
          type="button"
          className="self-start text-sm font-medium text-[var(--turquoise)] underline-offset-2 hover:underline"
          onClick={() => append({ ...DEFAULT_ROOM, children_ages: [] })}
        >
          + Add room
        </button>
      ) : null}
      <p className="text-sm text-ink-muted">
        Searching flights for {totalAdults} adult{totalAdults === 1 ? "" : "s"}
        {totalChildren
          ? `, ${totalChildren} child${totalChildren === 1 ? "" : "ren"}`
          : ""}
      </p>
    </div>
  );
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
        rooms: [{ ...DEFAULT_ROOM, children_ages: [] }],
        max_stops: undefined,
        max_price: undefined,
        skip_hotel: leg.skip_hotel ?? false,
        star_class: [],
        free_cancellation_only: false,
        hotel_price_min: undefined,
        hotel_price_max: undefined,
      })),
    },
  });

  const { fields } = useFieldArray({ control, name: "legs" });
  const watchedLegs = watch("legs");

  async function onSubmit(values: FormValues) {
    // Sequential per leg (patch then research) so a failure attributes cleanly;
    // wrap each sequence in allSettled so one rejection doesn't abort the rest.
    const results: PromiseSettledResult<void>[] = [];
    for (const row of values.legs) {
      const [settled] = await Promise.allSettled([
        (async () => {
          const filters = buildFilters(row);
          const body: LegPatchIn = { skip_hotel: row.skip_hotel };
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

                  <LegRoomsFields
                    legIndex={index}
                    control={control}
                    register={register}
                    setValue={setValue}
                    watch={watch}
                    errors={errors.legs?.[index]}
                  />

                  <div className="flex flex-col gap-3">
                    <p className="text-xs font-bold tracking-[0.14em] text-ink-muted uppercase">
                      Flights
                    </p>
                    <div className="grid gap-3 sm:grid-cols-2">
                      <div className="flex flex-col gap-1.5">
                        <Label htmlFor={`legs.${index}.max_stops`}>Max stops</Label>
                        <select
                          id={`legs.${index}.max_stops`}
                          className={selectClassName}
                          {...register(`legs.${index}.max_stops`, {
                            setValueAs: (value) =>
                              value === "" || value === undefined
                                ? undefined
                                : Number(value),
                          })}
                        >
                          <option value="">Any</option>
                          <option value={0}>Nonstop</option>
                          <option value={1}>1 stop or fewer</option>
                        </select>
                      </div>
                      <div className="flex flex-col gap-1.5">
                        <Label htmlFor={`legs.${index}.max_price`}>
                          Max price ({homeCurrency})
                        </Label>
                        <Input
                          id={`legs.${index}.max_price`}
                          type="number"
                          min={0}
                          step="1"
                          placeholder="Any"
                          {...register(`legs.${index}.max_price`, {
                            setValueAs: (value) => {
                              if (
                                value === "" ||
                                value === null ||
                                value === undefined
                              ) {
                                return undefined;
                              }
                              const n = Number(value);
                              return Number.isFinite(n) ? n : undefined;
                            },
                          })}
                        />
                        {errors.legs?.[index]?.max_price && (
                          <p className="text-sm text-destructive">
                            {errors.legs[index]?.max_price?.message}
                          </p>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="flex flex-col gap-3">
                    <p className="text-xs font-bold tracking-[0.14em] text-ink-muted uppercase">
                      Hotels
                    </p>
                    <label className="flex items-start gap-2 text-sm text-ink">
                      <input
                        type="checkbox"
                        className="mt-0.5 size-4 shrink-0 accent-[var(--turquoise)]"
                        {...register(`legs.${index}.skip_hotel`)}
                      />
                      <span>
                        Staying at a family/friend&apos;s place — skip hotel search for
                        this leg.
                      </span>
                    </label>
                    <div
                      className={
                        watchedLegs?.[index]?.skip_hotel
                          ? "flex flex-col gap-3 opacity-40 pointer-events-none"
                          : "flex flex-col gap-3"
                      }
                      aria-disabled={watchedLegs?.[index]?.skip_hotel ?? false}
                    >
                      <div className="flex flex-col gap-1.5">
                        <span className="text-sm font-medium">Star class</span>
                        <div className="flex flex-wrap gap-3">
                          {[1, 2, 3, 4, 5].map((star) => (
                            <label
                              key={star}
                              className="flex items-center gap-1.5 text-sm text-ink"
                            >
                              <input
                                type="checkbox"
                                value={star}
                                className="size-4 accent-[var(--turquoise)]"
                                {...register(`legs.${index}.star_class`)}
                              />
                              {star}
                            </label>
                          ))}
                        </div>
                      </div>
                      <label className="flex items-center gap-2 text-sm text-ink">
                        <input
                          type="checkbox"
                          className="size-4 accent-[var(--turquoise)]"
                          {...register(`legs.${index}.free_cancellation_only`)}
                        />
                        Free cancellation only
                      </label>
                      <div className="grid gap-3 sm:grid-cols-2">
                        <div className="flex flex-col gap-1.5">
                          <Label htmlFor={`legs.${index}.hotel_price_min`}>
                            Min price ({homeCurrency})
                          </Label>
                          <Input
                            id={`legs.${index}.hotel_price_min`}
                            type="number"
                            min={0}
                            step="1"
                            placeholder="Any"
                            tabIndex={watchedLegs?.[index]?.skip_hotel ? -1 : undefined}
                            {...register(`legs.${index}.hotel_price_min`, {
                              setValueAs: (value) => {
                                if (
                                  value === "" ||
                                  value === null ||
                                  value === undefined
                                ) {
                                  return undefined;
                                }
                                const n = Number(value);
                                return Number.isFinite(n) ? n : undefined;
                              },
                            })}
                          />
                        </div>
                        <div className="flex flex-col gap-1.5">
                          <Label htmlFor={`legs.${index}.hotel_price_max`}>
                            Max price ({homeCurrency})
                          </Label>
                          <Input
                            id={`legs.${index}.hotel_price_max`}
                            type="number"
                            min={0}
                            step="1"
                            placeholder="Any"
                            tabIndex={watchedLegs?.[index]?.skip_hotel ? -1 : undefined}
                            {...register(`legs.${index}.hotel_price_max`, {
                              setValueAs: (value) => {
                                if (
                                  value === "" ||
                                  value === null ||
                                  value === undefined
                                ) {
                                  return undefined;
                                }
                                const n = Number(value);
                                return Number.isFinite(n) ? n : undefined;
                              },
                            })}
                          />
                        </div>
                      </div>
                    </div>
                  </div>
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

"use client";

import { useState } from "react";
import {
  useFieldArray,
  type Control,
  type FieldArrayPath,
  type FieldErrors,
  type FieldValues,
  type Path,
  type UseFormRegister,
  type UseFormSetValue,
  type UseFormWatch,
} from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  HOTEL_AMENITIES,
  HOTEL_PROPERTY_TYPES,
  VR_AMENITIES,
  VR_PROPERTY_TYPES,
} from "@/lib/google-hotels-filters";
import { countAdvancedFilters } from "@/lib/leg-filters-map";

export const optionalNumber = z.preprocess((value) => {
  if (value === "" || value === null || value === undefined) return undefined;
  if (typeof value === "number" && Number.isNaN(value)) return undefined;
  return value;
}, z.number().nonnegative().optional());

export const roomSchema = z
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

export const optionalInt = z.preprocess((value) => {
  if (value === "" || value === null || value === undefined) return undefined;
  if (typeof value === "number" && Number.isNaN(value)) return undefined;
  return value;
}, z.number().int().nonnegative().optional());

export const legFiltersFieldsSchema = z.object({
  rooms: z.array(roomSchema).min(1).max(20),
  max_stops: z.preprocess((value) => {
    if (value === "" || value === null || value === undefined) return undefined;
    return value;
  }, z.number().int().min(0).max(2).optional()),
  max_price: optionalNumber,
  skip_hotel: z.boolean().default(false),
  skip_flight: z.boolean().default(false),
  star_class: z.array(z.coerce.number().int().min(1).max(5)).default([]),
  free_cancellation_only: z.boolean().default(false),
  hotel_price_min: optionalNumber,
  hotel_price_max: optionalNumber,
  deep_search: z.boolean().optional(),
  travel_class: z.union([z.literal(1), z.literal(2), z.literal(3), z.literal(4)]).optional(),
  show_hidden: z.boolean().default(false),
  exclude_basic: z.boolean().default(false),
  flight_sort_by: z
    .union([z.literal(1), z.literal(2), z.literal(3), z.literal(4), z.literal(5), z.literal(6)])
    .optional(),
  include_airlines: z.array(z.string()).default([]),
  exclude_airlines: z.array(z.string()).default([]),
  bags: optionalInt,
  departure_start_hour: optionalInt,
  departure_end_hour: optionalInt,
  arrival_start_hour: optionalInt,
  arrival_end_hour: optionalInt,
  emissions: z.boolean().default(false),
  layover_min_minutes: optionalInt,
  layover_max_minutes: optionalInt,
  exclude_conns: z.array(z.string()).default([]),
  max_duration_minutes: optionalInt,
  infants_in_seat: optionalInt,
  infants_on_lap: optionalInt,
  property_types: z.array(z.coerce.number().int()).default([]),
  amenity_ids: z.array(z.coerce.number().int()).default([]),
  min_rating: z.union([z.literal(7), z.literal(8), z.literal(9)]).optional(),
  hotel_sort_by: z.union([z.literal(3), z.literal(8), z.literal(13)]).optional(),
  eco_certified_only: z.boolean().default(false),
  special_offers_only: z.boolean().default(false),
  brands: z.array(z.coerce.number().int()).default([]),
  vacation_rentals: z.boolean().default(false),
  bedrooms: optionalInt,
  bathrooms: optionalInt,
});

export type LegFiltersFieldsShape = z.infer<typeof legFiltersFieldsSchema>;

export const DEFAULT_ROOM = { adults: 2, children: 0, children_ages: [] as number[] };

export const DEFAULT_LEG_FILTERS: LegFiltersFieldsShape = {
  rooms: [{ ...DEFAULT_ROOM, children_ages: [] }],
  max_stops: undefined,
  max_price: undefined,
  skip_hotel: false,
  skip_flight: false,
  star_class: [],
  free_cancellation_only: false,
  hotel_price_min: undefined,
  hotel_price_max: undefined,
  deep_search: undefined,
  travel_class: undefined,
  show_hidden: false,
  exclude_basic: false,
  flight_sort_by: undefined,
  include_airlines: [],
  exclude_airlines: [],
  bags: undefined,
  departure_start_hour: undefined,
  departure_end_hour: undefined,
  arrival_start_hour: undefined,
  arrival_end_hour: undefined,
  emissions: false,
  layover_min_minutes: undefined,
  layover_max_minutes: undefined,
  exclude_conns: [],
  max_duration_minutes: undefined,
  infants_in_seat: undefined,
  infants_on_lap: undefined,
  property_types: [],
  amenity_ids: [],
  min_rating: undefined,
  hotel_sort_by: undefined,
  eco_certified_only: false,
  special_offers_only: false,
  brands: [],
  vacation_rentals: false,
  bedrooms: undefined,
  bathrooms: undefined,
};

const selectClassName =
  "h-9 w-full rounded-[var(--radius-chip)] border border-border-interactive bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50";

function parseCsvTokens(raw: string): string[] {
  return raw
    .split(",")
    .map((part) => part.trim().toUpperCase())
    .filter((part) => part.length > 0);
}

function parseCsvInts(raw: string): number[] {
  return raw
    .split(",")
    .map((part) => part.trim())
    .filter((part) => /^\d+$/.test(part))
    .map((part) => Number(part));
}

function optionalNumberAs(value: unknown): number | undefined {
  if (value === "" || value === null || value === undefined) return undefined;
  const n = Number(value);
  return Number.isFinite(n) ? n : undefined;
}

type WithFilterLegs = FieldValues & { legs: LegFiltersFieldsShape[] };

interface LegFiltersFieldsProps<T extends WithFilterLegs> {
  legIndex: number;
  homeCurrency: string;
  control: Control<T>;
  register: UseFormRegister<T>;
  setValue: UseFormSetValue<T>;
  watch: UseFormWatch<T>;
  errors: FieldErrors<LegFiltersFieldsShape> | undefined;
}

export function LegFiltersFields<T extends WithFilterLegs>({
  legIndex,
  homeCurrency,
  control,
  register,
  setValue,
  watch,
  errors,
}: LegFiltersFieldsProps<T>) {
  const roomsPath = `legs.${legIndex}.rooms` as FieldArrayPath<T>;
  const { fields, append, remove } = useFieldArray({
    control,
    name: roomsPath,
  });
  const rooms =
    (watch(`legs.${legIndex}.rooms` as Path<T>) as LegFiltersFieldsShape["rooms"] | undefined) ??
    [];
  const skipHotel = Boolean(watch(`legs.${legIndex}.skip_hotel` as Path<T>));
  const skipFlight = Boolean(watch(`legs.${legIndex}.skip_flight` as Path<T>));
  const vacationRentals = Boolean(
    watch(`legs.${legIndex}.vacation_rentals` as Path<T>)
  );
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const watchedLeg = watch(`legs.${legIndex}` as Path<T>) as
    | LegFiltersFieldsShape
    | undefined;
  const advancedCount = countAdvancedFilters({
    ...DEFAULT_LEG_FILTERS,
    ...watchedLeg,
    rooms: watchedLeg?.rooms ?? DEFAULT_LEG_FILTERS.rooms,
  });
  const totalAdults = rooms.reduce((sum, room) => sum + (Number(room?.adults) || 0), 0);
  const totalChildren = rooms.reduce(
    (sum, room) => sum + (Number(room?.children) || 0),
    0
  );

  function syncChildrenAges(roomIndex: number, nextChildren: number) {
    const current =
      (watch(
        `legs.${legIndex}.rooms.${roomIndex}.children_ages` as Path<T>
      ) as number[] | undefined) ?? [];
    const nextAges = Array.from({ length: nextChildren }, (_, i) =>
      current[i] !== undefined && current[i] !== null ? Number(current[i]) : 0
    );
    setValue(
      `legs.${legIndex}.rooms.${roomIndex}.children_ages` as Path<T>,
      nextAges as never,
      { shouldValidate: true }
    );
  }

  return (
    <div className="flex flex-col gap-4">
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
              `legs.${legIndex}.rooms.${roomIndex}.children` as Path<T>,
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
                      {...register(
                        `legs.${legIndex}.rooms.${roomIndex}.adults` as Path<T>,
                        {
                          setValueAs: (value) => {
                            const n = Number(value);
                            return Number.isFinite(n) ? n : 1;
                          },
                        }
                      )}
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
                        <div key={ageIndex} className="flex flex-col gap-1">
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
                              `legs.${legIndex}.rooms.${roomIndex}.children_ages.${ageIndex}` as Path<T>,
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
            onClick={() => append({ ...DEFAULT_ROOM, children_ages: [] } as never)}
          >
            + Add room
          </button>
        ) : null}
        <p className="text-sm text-ink-muted">
          Party: {totalAdults} adult{totalAdults === 1 ? "" : "s"}
          {totalChildren
            ? `, ${totalChildren} child${totalChildren === 1 ? "" : "ren"}`
            : ""}
        </p>
      </div>

      <div className="flex flex-col gap-3">
        <p className="text-xs font-bold tracking-[0.14em] text-ink-muted uppercase">
          Flights
        </p>
        <label className="flex items-start gap-2 text-sm text-ink">
          <input
            type="checkbox"
            className="mt-0.5 size-4 shrink-0 accent-[var(--turquoise)]"
            {...register(`legs.${legIndex}.skip_flight` as Path<T>)}
          />
          <span>
            Ferry / ground transfer — skip flight search for this leg (no airport
            needed).
          </span>
        </label>
        <div
          className={
            skipFlight
              ? "flex flex-col gap-3 opacity-40 pointer-events-none"
              : "flex flex-col gap-3"
          }
          aria-disabled={skipFlight}
        >
          <p className="text-sm text-ink-muted">
            Searching flights for {totalAdults} adult{totalAdults === 1 ? "" : "s"}
            {totalChildren
              ? `, ${totalChildren} child${totalChildren === 1 ? "" : "ren"}`
              : ""}
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor={`legs.${legIndex}.max_stops`}>Max stops</Label>
              <select
                id={`legs.${legIndex}.max_stops`}
                className={selectClassName}
                tabIndex={skipFlight ? -1 : undefined}
                {...register(`legs.${legIndex}.max_stops` as Path<T>, {
                  setValueAs: (value) =>
                    value === "" || value === undefined ? undefined : Number(value),
                })}
              >
                <option value="">Any</option>
                <option value={0}>Nonstop</option>
                <option value={1}>1 stop or fewer</option>
              </select>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor={`legs.${legIndex}.max_price`}>
                Max price ({homeCurrency || "—"})
              </Label>
              <Input
                id={`legs.${legIndex}.max_price`}
                type="number"
                min={0}
                step="1"
                placeholder="Any"
                tabIndex={skipFlight ? -1 : undefined}
                {...register(`legs.${legIndex}.max_price` as Path<T>, {
                  setValueAs: (value) => {
                    if (value === "" || value === null || value === undefined) {
                      return undefined;
                    }
                    const n = Number(value);
                    return Number.isFinite(n) ? n : undefined;
                  },
                })}
              />
              {errors?.max_price && (
                <p className="text-sm text-destructive">{errors.max_price.message}</p>
              )}
            </div>
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
            {...register(`legs.${legIndex}.skip_hotel` as Path<T>)}
          />
          <span>
            Staying at a family/friend&apos;s place — skip hotel search for this leg.
          </span>
        </label>
        <div
          className={
            skipHotel
              ? "flex flex-col gap-3 opacity-40 pointer-events-none"
              : "flex flex-col gap-3"
          }
          aria-disabled={skipHotel}
        >
          <div className="flex flex-col gap-1.5">
            <span className="text-sm font-medium">Star class</span>
            <div className="flex flex-wrap gap-3">
              {[1, 2, 3, 4, 5].map((star) => (
                <label key={star} className="flex items-center gap-1.5 text-sm text-ink">
                  <input
                    type="checkbox"
                    value={star}
                    className="size-4 accent-[var(--turquoise)]"
                    {...register(`legs.${legIndex}.star_class` as Path<T>)}
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
              {...register(`legs.${legIndex}.free_cancellation_only` as Path<T>)}
            />
            Free cancellation only
          </label>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor={`legs.${legIndex}.hotel_price_min`}>
                Min price ({homeCurrency || "—"})
              </Label>
              <Input
                id={`legs.${legIndex}.hotel_price_min`}
                type="number"
                min={0}
                step="1"
                placeholder="Any"
                tabIndex={skipHotel ? -1 : undefined}
                {...register(`legs.${legIndex}.hotel_price_min` as Path<T>, {
                  setValueAs: (value) => {
                    if (value === "" || value === null || value === undefined) {
                      return undefined;
                    }
                    const n = Number(value);
                    return Number.isFinite(n) ? n : undefined;
                  },
                })}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor={`legs.${legIndex}.hotel_price_max`}>
                Max price ({homeCurrency || "—"})
              </Label>
              <Input
                id={`legs.${legIndex}.hotel_price_max`}
                type="number"
                min={0}
                step="1"
                placeholder="Any"
                tabIndex={skipHotel ? -1 : undefined}
                {...register(`legs.${legIndex}.hotel_price_max` as Path<T>, {
                  setValueAs: (value) => {
                    if (value === "" || value === null || value === undefined) {
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

      <div className="flex flex-col gap-3">
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="self-start border-border-interactive"
          aria-expanded={advancedOpen}
          onClick={() => setAdvancedOpen((open) => !open)}
        >
          {advancedCount > 0
            ? `Advanced search · ${advancedCount} set`
            : "Advanced search"}
        </Button>
        {advancedOpen ? (
          <div className="flex flex-col gap-6 rounded-[12px] border border-border-interactive p-4">
            <div
              className={
                skipFlight
                  ? "flex flex-col gap-3 opacity-40 pointer-events-none"
                  : "flex flex-col gap-3"
              }
              aria-disabled={skipFlight}
            >
              <p className="text-xs font-bold tracking-[0.14em] text-ink-muted uppercase">
                Flight details
              </p>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor={`legs.${legIndex}.travel_class`}>Cabin class</Label>
                  <select
                    id={`legs.${legIndex}.travel_class`}
                    className={selectClassName}
                    {...register(`legs.${legIndex}.travel_class` as Path<T>, {
                      setValueAs: (value) =>
                        value === "" || value === undefined ? undefined : Number(value),
                    })}
                  >
                    <option value="">Any (economy default)</option>
                    <option value={1}>Economy</option>
                    <option value={2}>Premium economy</option>
                    <option value={3}>Business</option>
                    <option value={4}>First</option>
                  </select>
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor={`legs.${legIndex}.flight_sort_by`}>Sort by</Label>
                  <select
                    id={`legs.${legIndex}.flight_sort_by`}
                    className={selectClassName}
                    {...register(`legs.${legIndex}.flight_sort_by` as Path<T>, {
                      setValueAs: (value) =>
                        value === "" || value === undefined ? undefined : Number(value),
                    })}
                  >
                    <option value="">Top flights</option>
                    <option value={1}>Top</option>
                    <option value={2}>Price</option>
                    <option value={3}>Departure time</option>
                    <option value={4}>Arrival time</option>
                    <option value={5}>Duration</option>
                    <option value={6}>Emissions</option>
                  </select>
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor={`legs.${legIndex}.bags`}>Carry-on bags</Label>
                  <Input
                    id={`legs.${legIndex}.bags`}
                    type="number"
                    min={0}
                    {...register(`legs.${legIndex}.bags` as Path<T>, {
                      setValueAs: optionalNumberAs,
                    })}
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor={`legs.${legIndex}.max_duration_minutes`}>
                    Max duration (minutes)
                  </Label>
                  <Input
                    id={`legs.${legIndex}.max_duration_minutes`}
                    type="number"
                    min={1}
                    {...register(`legs.${legIndex}.max_duration_minutes` as Path<T>, {
                      setValueAs: optionalNumberAs,
                    })}
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor={`legs.${legIndex}.layover_min_minutes`}>
                    Layover min (minutes)
                  </Label>
                  <Input
                    id={`legs.${legIndex}.layover_min_minutes`}
                    type="number"
                    min={0}
                    {...register(`legs.${legIndex}.layover_min_minutes` as Path<T>, {
                      setValueAs: optionalNumberAs,
                    })}
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor={`legs.${legIndex}.layover_max_minutes`}>
                    Layover max (minutes)
                  </Label>
                  <Input
                    id={`legs.${legIndex}.layover_max_minutes`}
                    type="number"
                    min={0}
                    {...register(`legs.${legIndex}.layover_max_minutes` as Path<T>, {
                      setValueAs: optionalNumberAs,
                    })}
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor={`legs.${legIndex}.infants_in_seat`}>Infants in seat</Label>
                  <Input
                    id={`legs.${legIndex}.infants_in_seat`}
                    type="number"
                    min={0}
                    {...register(`legs.${legIndex}.infants_in_seat` as Path<T>, {
                      setValueAs: optionalNumberAs,
                    })}
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor={`legs.${legIndex}.infants_on_lap`}>Infants on lap</Label>
                  <Input
                    id={`legs.${legIndex}.infants_on_lap`}
                    type="number"
                    min={0}
                    {...register(`legs.${legIndex}.infants_on_lap` as Path<T>, {
                      setValueAs: optionalNumberAs,
                    })}
                  />
                </div>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor={`legs.${legIndex}.departure_start_hour`}>
                    Depart after (hour 0–23)
                  </Label>
                  <Input
                    id={`legs.${legIndex}.departure_start_hour`}
                    type="number"
                    min={0}
                    max={23}
                    {...register(`legs.${legIndex}.departure_start_hour` as Path<T>, {
                      setValueAs: optionalNumberAs,
                    })}
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor={`legs.${legIndex}.departure_end_hour`}>
                    Depart before (hour)
                  </Label>
                  <Input
                    id={`legs.${legIndex}.departure_end_hour`}
                    type="number"
                    min={0}
                    max={23}
                    {...register(`legs.${legIndex}.departure_end_hour` as Path<T>, {
                      setValueAs: optionalNumberAs,
                    })}
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor={`legs.${legIndex}.arrival_start_hour`}>
                    Arrive after (hour)
                  </Label>
                  <Input
                    id={`legs.${legIndex}.arrival_start_hour`}
                    type="number"
                    min={0}
                    max={23}
                    {...register(`legs.${legIndex}.arrival_start_hour` as Path<T>, {
                      setValueAs: optionalNumberAs,
                    })}
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor={`legs.${legIndex}.arrival_end_hour`}>
                    Arrive before (hour)
                  </Label>
                  <Input
                    id={`legs.${legIndex}.arrival_end_hour`}
                    type="number"
                    min={0}
                    max={23}
                    {...register(`legs.${legIndex}.arrival_end_hour` as Path<T>, {
                      setValueAs: optionalNumberAs,
                    })}
                  />
                </div>
              </div>
              <AirlineListFields
                legIndex={legIndex}
                include={
                  (watch(`legs.${legIndex}.include_airlines` as Path<T>) as string[] | undefined) ??
                  []
                }
                exclude={
                  (watch(`legs.${legIndex}.exclude_airlines` as Path<T>) as string[] | undefined) ??
                  []
                }
                setValue={setValue}
              />
              <div className="flex flex-col gap-1.5">
                <Label htmlFor={`legs.${legIndex}.exclude_conns`}>
                  Skip connecting airports (IATA, comma-separated)
                </Label>
                <Input
                  id={`legs.${legIndex}.exclude_conns`}
                  key={(
                    (watch(`legs.${legIndex}.exclude_conns` as Path<T>) as string[] | undefined) ??
                    []
                  ).join(",")}
                  defaultValue={(
                    (watch(`legs.${legIndex}.exclude_conns` as Path<T>) as string[] | undefined) ??
                    []
                  ).join(", ")}
                  onBlur={(event) => {
                    setValue(
                      `legs.${legIndex}.exclude_conns` as Path<T>,
                      parseCsvTokens(event.target.value) as never
                    );
                  }}
                />
              </div>
              <label className="flex items-center gap-2 text-sm text-ink">
                <input
                  type="checkbox"
                  className="size-4 accent-[var(--turquoise)]"
                  checked={watch(`legs.${legIndex}.deep_search` as Path<T>) === false}
                  onChange={(event) => {
                    setValue(
                      `legs.${legIndex}.deep_search` as Path<T>,
                      (event.target.checked ? false : undefined) as never
                    );
                  }}
                />
                Skip deep search (faster, fewer results)
              </label>
              <label className="flex items-center gap-2 text-sm text-ink">
                <input
                  type="checkbox"
                  className="size-4 accent-[var(--turquoise)]"
                  {...register(`legs.${legIndex}.show_hidden` as Path<T>)}
                />
                View more flights
              </label>
              <label className="flex items-center gap-2 text-sm text-ink">
                <input
                  type="checkbox"
                  className="size-4 accent-[var(--turquoise)]"
                  {...register(`legs.${legIndex}.exclude_basic` as Path<T>)}
                />
                Exclude basic economy (US domestic)
              </label>
              <label className="flex items-center gap-2 text-sm text-ink">
                <input
                  type="checkbox"
                  className="size-4 accent-[var(--turquoise)]"
                  {...register(`legs.${legIndex}.emissions` as Path<T>)}
                />
                Less emissions only
              </label>
            </div>

            <div
              className={
                skipHotel
                  ? "flex flex-col gap-3 opacity-40 pointer-events-none"
                  : "flex flex-col gap-3"
              }
              aria-disabled={skipHotel}
            >
              <p className="text-xs font-bold tracking-[0.14em] text-ink-muted uppercase">
                Hotel details
              </p>
              <label className="flex items-center gap-2 text-sm text-ink">
                <input
                  type="checkbox"
                  className="size-4 accent-[var(--turquoise)]"
                  {...register(`legs.${legIndex}.vacation_rentals` as Path<T>)}
                  onChange={(event) => {
                    void register(`legs.${legIndex}.vacation_rentals` as Path<T>).onChange(
                      event
                    );
                    setValue(`legs.${legIndex}.property_types` as Path<T>, [] as never);
                    setValue(`legs.${legIndex}.amenity_ids` as Path<T>, [] as never);
                    if (!event.target.checked) {
                      setValue(`legs.${legIndex}.bedrooms` as Path<T>, undefined as never);
                      setValue(`legs.${legIndex}.bathrooms` as Path<T>, undefined as never);
                    }
                  }}
                />
                Vacation rentals
              </label>
              <IdCheckboxGroup
                legend="Property types"
                items={vacationRentals ? VR_PROPERTY_TYPES : HOTEL_PROPERTY_TYPES}
                values={
                  (watch(`legs.${legIndex}.property_types` as Path<T>) as number[] | undefined) ??
                  []
                }
                onChange={(next) =>
                  setValue(`legs.${legIndex}.property_types` as Path<T>, next as never)
                }
              />
              <IdCheckboxGroup
                legend="Amenities"
                items={vacationRentals ? VR_AMENITIES : HOTEL_AMENITIES}
                values={
                  (watch(`legs.${legIndex}.amenity_ids` as Path<T>) as number[] | undefined) ?? []
                }
                onChange={(next) =>
                  setValue(`legs.${legIndex}.amenity_ids` as Path<T>, next as never)
                }
              />
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor={`legs.${legIndex}.min_rating`}>Guest rating</Label>
                  <select
                    id={`legs.${legIndex}.min_rating`}
                    className={selectClassName}
                    {...register(`legs.${legIndex}.min_rating` as Path<T>, {
                      setValueAs: (value) =>
                        value === "" || value === undefined ? undefined : Number(value),
                    })}
                  >
                    <option value="">Any</option>
                    <option value={7}>3.5+</option>
                    <option value={8}>4.0+</option>
                    <option value={9}>4.5+</option>
                  </select>
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor={`legs.${legIndex}.hotel_sort_by`}>Sort by</Label>
                  <select
                    id={`legs.${legIndex}.hotel_sort_by`}
                    className={selectClassName}
                    {...register(`legs.${legIndex}.hotel_sort_by` as Path<T>, {
                      setValueAs: (value) =>
                        value === "" || value === undefined ? undefined : Number(value),
                    })}
                  >
                    <option value="">Default</option>
                    <option value={3}>Lowest price</option>
                    <option value={8}>Highest rating</option>
                    <option value={13}>Most reviewed</option>
                  </select>
                </div>
              </div>
              <label className="flex items-center gap-2 text-sm text-ink">
                <input
                  type="checkbox"
                  className="size-4 accent-[var(--turquoise)]"
                  {...register(`legs.${legIndex}.eco_certified_only` as Path<T>)}
                />
                Eco-certified only
              </label>
              <label className="flex items-center gap-2 text-sm text-ink">
                <input
                  type="checkbox"
                  className="size-4 accent-[var(--turquoise)]"
                  {...register(`legs.${legIndex}.special_offers_only` as Path<T>)}
                />
                Special offers only
              </label>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor={`legs.${legIndex}.brands`}>
                  Brand IDs (numeric, comma-separated)
                </Label>
                <Input
                  id={`legs.${legIndex}.brands`}
                  key={(
                    (watch(`legs.${legIndex}.brands` as Path<T>) as number[] | undefined) ?? []
                  ).join(",")}
                  defaultValue={(
                    (watch(`legs.${legIndex}.brands` as Path<T>) as number[] | undefined) ?? []
                  ).join(", ")}
                  onBlur={(event) => {
                    setValue(
                      `legs.${legIndex}.brands` as Path<T>,
                      parseCsvInts(event.target.value) as never
                    );
                  }}
                />
                <p className="text-xs text-ink-muted">
                  IDs come from a prior Google Hotels search. Leave blank unless you have them.
                </p>
              </div>
              {vacationRentals ? (
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor={`legs.${legIndex}.bedrooms`}>Bedrooms</Label>
                    <Input
                      id={`legs.${legIndex}.bedrooms`}
                      type="number"
                      min={1}
                      {...register(`legs.${legIndex}.bedrooms` as Path<T>, {
                        setValueAs: optionalNumberAs,
                      })}
                    />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor={`legs.${legIndex}.bathrooms`}>Bathrooms</Label>
                    <Input
                      id={`legs.${legIndex}.bathrooms`}
                      type="number"
                      min={1}
                      {...register(`legs.${legIndex}.bathrooms` as Path<T>, {
                        setValueAs: optionalNumberAs,
                      })}
                    />
                  </div>
                </div>
              ) : null}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function IdCheckboxGroup({
  legend,
  items,
  values,
  onChange,
}: {
  legend: string;
  items: { id: number; name: string }[];
  values: number[];
  onChange: (next: number[]) => void;
}) {
  const selected = new Set(values.map(Number));
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="text-sm font-medium text-ink">{legend}</legend>
      <div className="grid gap-2 sm:grid-cols-2">
        {items.map((item) => {
          const checked = selected.has(item.id);
          return (
            <label key={item.id} className="flex items-center gap-1.5 text-sm text-ink">
              <input
                type="checkbox"
                className="size-4 accent-[var(--turquoise)]"
                checked={checked}
                onChange={() => {
                  const next = new Set(selected);
                  if (checked) next.delete(item.id);
                  else next.add(item.id);
                  onChange([...next].sort((a, b) => a - b));
                }}
              />
              {item.name}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

function AirlineListFields<T extends WithFilterLegs>({
  legIndex,
  include,
  exclude,
  setValue,
}: {
  legIndex: number;
  include: string[];
  exclude: string[];
  setValue: UseFormSetValue<T>;
}) {
  const mode: "include" | "exclude" = exclude.length > 0 && include.length === 0
    ? "exclude"
    : "include";
  const codes = mode === "exclude" ? exclude : include;
  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor={`legs.${legIndex}.airline_codes`}>Airlines (IATA / alliances)</Label>
      <div className="grid gap-3 sm:grid-cols-[12rem_minmax(0,1fr)]">
        <select
          className={selectClassName}
          value={mode}
          onChange={(event) => {
            const nextMode = event.target.value as "include" | "exclude";
            if (nextMode === "include") {
              setValue(`legs.${legIndex}.include_airlines` as Path<T>, codes as never);
              setValue(`legs.${legIndex}.exclude_airlines` as Path<T>, [] as never);
            } else {
              setValue(`legs.${legIndex}.exclude_airlines` as Path<T>, codes as never);
              setValue(`legs.${legIndex}.include_airlines` as Path<T>, [] as never);
            }
          }}
        >
          <option value="include">Include only</option>
          <option value="exclude">Exclude</option>
        </select>
        <Input
          id={`legs.${legIndex}.airline_codes`}
          key={`${mode}:${codes.join(",")}`}
          defaultValue={codes.join(", ")}
          placeholder="TG, STAR_ALLIANCE"
          onBlur={(event) => {
            const next = parseCsvTokens(event.target.value);
            if (mode === "include") {
              setValue(`legs.${legIndex}.include_airlines` as Path<T>, next as never);
              setValue(`legs.${legIndex}.exclude_airlines` as Path<T>, [] as never);
            } else {
              setValue(`legs.${legIndex}.exclude_airlines` as Path<T>, next as never);
              setValue(`legs.${legIndex}.include_airlines` as Path<T>, [] as never);
            }
          }}
        />
      </div>
      <p className="text-xs text-ink-muted">
        Include and exclude cannot both be set. Alliances: STAR_ALLIANCE, SKYTEAM, ONEWORLD.
      </p>
    </div>
  );
}

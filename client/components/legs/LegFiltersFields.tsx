"use client";

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

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

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

export const legFiltersFieldsSchema = z.object({
  rooms: z.array(roomSchema).min(1).max(20),
  max_stops: z.preprocess((value) => {
    if (value === "" || value === null || value === undefined) return undefined;
    return value;
  }, z.number().int().min(0).max(1).optional()),
  max_price: optionalNumber,
  skip_hotel: z.boolean().default(false),
  skip_flight: z.boolean().default(false),
  star_class: z.array(z.coerce.number().int().min(1).max(5)).default([]),
  free_cancellation_only: z.boolean().default(false),
  hotel_price_min: optionalNumber,
  hotel_price_max: optionalNumber,
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
};

const selectClassName =
  "h-9 w-full rounded-[var(--radius-chip)] border border-border-interactive bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50";

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
    </div>
  );
}

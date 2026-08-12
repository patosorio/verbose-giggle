"use client";

import {
  useFieldArray,
  type Control,
  type FieldErrors,
  type UseFormRegister,
  type UseFormSetValue,
  type UseFormWatch,
} from "react-hook-form";

import {
  DEFAULT_LEG_FILTERS,
  LegFiltersFields,
} from "@/components/legs/LegFiltersFields";
import { LegRouteFields } from "@/components/legs/LegRouteFields";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { AiPlannerFormValues } from "@/components/trips/ai-planner-types";

interface ItineraryBuilderProps {
  control: Control<AiPlannerFormValues>;
  register: UseFormRegister<AiPlannerFormValues>;
  setValue: UseFormSetValue<AiPlannerFormValues>;
  watch: UseFormWatch<AiPlannerFormValues>;
  errors: FieldErrors<AiPlannerFormValues>;
  onConfirm: () => void;
  isConfirming: boolean;
}

export function ItineraryBuilder({
  control,
  register,
  setValue,
  watch,
  errors,
  onConfirm,
  isConfirming,
}: ItineraryBuilderProps) {
  const { fields, append, remove } = useFieldArray({ control, name: "legs" });
  const homeCurrency = watch("home_currency") ?? "";

  return (
    <div className="flex flex-col gap-6">
      <section className="flex flex-col gap-4">
        <h2 className="text-xs font-bold tracking-[0.14em] text-ink uppercase">
          Trip
        </h2>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5 sm:col-span-2">
            <Label htmlFor="trip_name">Trip name</Label>
            <Input
              id="trip_name"
              placeholder="Southeast Asia 2026"
              aria-invalid={!!errors.name}
              {...register("name")}
            />
            {errors.name && (
              <p className="text-sm text-destructive">{errors.name.message}</p>
            )}
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="home_currency">Home currency</Label>
            <Input
              id="home_currency"
              placeholder="USD"
              maxLength={3}
              aria-invalid={!!errors.home_currency}
              {...register("home_currency", {
                onBlur: (event) => {
                  setValue("home_currency", event.target.value.trim().toUpperCase(), {
                    shouldValidate: true,
                  });
                },
              })}
            />
            {errors.home_currency && (
              <p className="text-sm text-destructive">{errors.home_currency.message}</p>
            )}
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="budget_band">Budget band</Label>
            <select
              id="budget_band"
              className="h-8 w-full rounded-lg border border-border bg-background px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
              aria-invalid={!!errors.budget_band}
              {...register("budget_band")}
            >
              <option value="budget">Budget</option>
              <option value="comfort">Comfort</option>
              <option value="premium">Premium</option>
            </select>
            {errors.budget_band && (
              <p className="text-sm text-destructive">{errors.budget_band.message}</p>
            )}
          </div>
          <div className="flex flex-col gap-1.5 sm:col-span-2">
            <Label htmlFor="budget_target_amount">Budget target (optional)</Label>
            <Input
              id="budget_target_amount"
              type="number"
              step="any"
              min="0"
              placeholder="5000"
              aria-invalid={!!errors.budget_target_amount}
              {...register("budget_target_amount")}
            />
            {errors.budget_target_amount && (
              <p className="text-sm text-destructive">
                {errors.budget_target_amount.message}
              </p>
            )}
          </div>
        </div>
      </section>

      <section className="flex flex-col gap-4">
        <h2 className="text-xs font-bold tracking-[0.14em] text-ink uppercase">
          Itinerary
        </h2>
        {fields.length === 0 ? (
          <p className="text-sm text-ink-muted">
            No legs yet — chat with the advisor or add a leg manually.
          </p>
        ) : null}
        <ul className="flex flex-col gap-4">
          {fields.map((field, index) => {
            const origin = watch(`legs.${index}.origin`)?.trim() ?? "";
            const destination = watch(`legs.${index}.destination`)?.trim() ?? "";
            const originIata = watch(`legs.${index}.origin_iata`);
            const destinationIata = watch(`legs.${index}.destination_iata`);
            const originCandidates = watch(`legs.${index}.origin_candidates`) ?? [];
            const destinationCandidates =
              watch(`legs.${index}.destination_candidates`) ?? [];
            const skipFlight = Boolean(watch(`legs.${index}.skip_flight`));
            const locked = Boolean(watch(`legs.${index}.locked`));

            return (
              <li
                key={field.id}
                className={
                  locked
                    ? "flex flex-col gap-4 rounded-card border-[3px] border-[var(--coral-pink)] bg-bg p-4 shadow-[3px_3px_0_0_var(--coral-pink)]"
                    : "flex flex-col gap-4 rounded-card border border-border-soft bg-bg p-4 shadow-card"
                }
              >
                <div className="flex items-center justify-between gap-3">
                  <h3 className="text-xs font-bold tracking-[0.14em] text-ink uppercase">
                    Leg {index + 1}
                    {locked ? " · locked" : ""}
                    {!watch(`legs.${index}.start_date`) ||
                    !watch(`legs.${index}.end_date`)
                      ? " · needs dates"
                      : ""}
                    {skipFlight ? " · ferry/ground" : ""}
                  </h3>
                  <div className="flex items-center gap-1">
                    <Button
                      type="button"
                      variant={locked ? "default" : "outline"}
                      size="sm"
                      onClick={() =>
                        setValue(`legs.${index}.locked`, !locked, {
                          shouldDirty: true,
                        })
                      }
                    >
                      {locked ? "Unlock" : "Lock"}
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => remove(index)}
                    >
                      Remove
                    </Button>
                  </div>
                </div>

                <LegRouteFields
                  legIndex={index}
                  register={register}
                  errors={errors.legs?.[index]}
                  originAirport={
                    skipFlight
                      ? undefined
                      : {
                          iata: originIata,
                          candidates: originCandidates,
                          onPickIata: (iata) => {
                            setValue(`legs.${index}.origin_iata`, iata, {
                              shouldValidate: true,
                            });
                          },
                          unresolvedHint:
                            origin && !originIata && originCandidates.length === 0
                              ? `Couldn't find an airport for “${origin}”.`
                              : undefined,
                        }
                  }
                  destinationAirport={
                    skipFlight
                      ? undefined
                      : {
                          iata: destinationIata,
                          candidates: destinationCandidates,
                          onPickIata: (iata) => {
                            setValue(`legs.${index}.destination_iata`, iata, {
                              shouldValidate: true,
                            });
                          },
                          unresolvedHint:
                            destination &&
                            !destinationIata &&
                            destinationCandidates.length === 0
                              ? `Couldn't find an airport for “${destination}”.`
                              : undefined,
                        }
                  }
                />
                {!skipFlight && errors.legs?.[index]?.origin_iata && (
                  <p className="text-sm text-destructive">
                    {errors.legs[index]?.origin_iata?.message}
                  </p>
                )}
                {!skipFlight && errors.legs?.[index]?.destination_iata && (
                  <p className="text-sm text-destructive">
                    {errors.legs[index]?.destination_iata?.message}
                  </p>
                )}

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

        <div className="flex flex-wrap items-center gap-3">
          <Button
            type="button"
            variant="outline"
            onClick={() =>
              append({
                origin: "",
                destination: "",
                start_date: "",
                end_date: "",
                origin_iata: null,
                destination_iata: null,
                origin_candidates: [],
                destination_candidates: [],
                locked: false,
                ...DEFAULT_LEG_FILTERS,
                rooms: [{ adults: 2, children: 0, children_ages: [] }],
              })
            }
          >
            Add leg
          </Button>
          <Button type="button" disabled={isConfirming} onClick={onConfirm}>
            {isConfirming ? "Creating…" : "Confirm & start research"}
          </Button>
        </div>
      </section>
    </div>
  );
}

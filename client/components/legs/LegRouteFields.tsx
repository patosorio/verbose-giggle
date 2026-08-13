"use client";

import type {
  FieldErrors,
  FieldValues,
  Path,
  UseFormRegister,
} from "react-hook-form";
import { z } from "zod";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { AirportCandidateOut } from "@/lib/types";

export const legRouteFieldsSchema = z
  .object({
    origin: z.string().trim().min(1, "Origin is required"),
    destination: z.string().trim().min(1, "Destination is required"),
    start_date: z.string().min(1, "Start date is required"),
    end_date: z.string().min(1, "End date is required"),
  })
  .refine((row) => row.end_date >= row.start_date, {
    message: "End date must be on or after start date",
    path: ["end_date"],
  });

export type LegRouteFieldsShape = z.infer<typeof legRouteFieldsSchema>;

type WithRouteLegs = FieldValues & {
  legs: Array<{
    origin: string;
    destination: string;
    start_date: string;
    end_date: string;
  }>;
};

export interface AirportResolutionProps {
  iata: string | null | undefined;
  candidates: AirportCandidateOut[];
  onPickIata: (iata: string) => void;
  unresolvedHint?: string;
}

interface LegRouteFieldsProps<T extends WithRouteLegs> {
  legIndex: number;
  register: UseFormRegister<T>;
  errors: FieldErrors<LegRouteFieldsShape> | undefined;
  originAirport?: AirportResolutionProps;
  destinationAirport?: AirportResolutionProps;
}

function AirportResolutionUi({
  label,
  resolution,
}: {
  label: string;
  resolution?: AirportResolutionProps;
}) {
  if (!resolution) return null;

  if (resolution.iata) {
    return (
      <span className="inline-flex items-center rounded-[12px] border border-border-interactive bg-[var(--surface-alt)] px-2 py-0.5 text-xs font-bold tracking-wide text-ink">
        {resolution.iata}
      </span>
    );
  }

  if (resolution.candidates.length > 0) {
    return (
      <label className="flex flex-col gap-1">
        <span className="text-xs text-ink-muted">Pick {label} airport</span>
        <select
          key={resolution.candidates.map((c) => c.iata).join("-")}
          className="h-9 rounded-[var(--radius-chip)] border border-border-interactive bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          defaultValue=""
          onChange={(event) => {
            const value = event.target.value;
            if (value) resolution.onPickIata(value);
          }}
        >
          <option value="" disabled>
            Select airport…
          </option>
          {resolution.candidates.map((candidate) => (
            <option key={candidate.iata} value={candidate.iata}>
              {candidate.iata} — {candidate.name}
            </option>
          ))}
        </select>
      </label>
    );
  }

  if (resolution.unresolvedHint) {
    return <p className="text-xs text-destructive">{resolution.unresolvedHint}</p>;
  }

  return null;
}

export function LegRouteFields<T extends WithRouteLegs>({
  legIndex,
  register,
  errors,
  originAirport,
  destinationAirport,
}: LegRouteFieldsProps<T>) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <div className="flex flex-col gap-1.5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Label htmlFor={`legs.${legIndex}.origin`}>Origin</Label>
          {originAirport?.iata ? (
            <AirportResolutionUi label="origin" resolution={originAirport} />
          ) : null}
        </div>
        <Input
          id={`legs.${legIndex}.origin`}
          placeholder="Bangkok"
          aria-invalid={!!errors?.origin}
          {...register(`legs.${legIndex}.origin` as Path<T>)}
        />
        {errors?.origin && (
          <p className="text-sm text-destructive">{errors.origin.message}</p>
        )}
        {originAirport && !originAirport.iata ? (
          <AirportResolutionUi label="origin" resolution={originAirport} />
        ) : null}
      </div>
      <div className="flex flex-col gap-1.5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Label htmlFor={`legs.${legIndex}.destination`}>Destination</Label>
          {destinationAirport?.iata ? (
            <AirportResolutionUi label="destination" resolution={destinationAirport} />
          ) : null}
        </div>
        <Input
          id={`legs.${legIndex}.destination`}
          placeholder="Phuket"
          aria-invalid={!!errors?.destination}
          {...register(`legs.${legIndex}.destination` as Path<T>)}
        />
        {errors?.destination && (
          <p className="text-sm text-destructive">{errors.destination.message}</p>
        )}
        {destinationAirport && !destinationAirport.iata ? (
          <AirportResolutionUi label="destination" resolution={destinationAirport} />
        ) : null}
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`legs.${legIndex}.start_date`}>Start date</Label>
        <Input
          id={`legs.${legIndex}.start_date`}
          type="date"
          aria-invalid={!!errors?.start_date}
          {...register(`legs.${legIndex}.start_date` as Path<T>)}
        />
        {errors?.start_date && (
          <p className="text-sm text-destructive">{errors.start_date.message}</p>
        )}
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`legs.${legIndex}.end_date`}>End date</Label>
        <Input
          id={`legs.${legIndex}.end_date`}
          type="date"
          aria-invalid={!!errors?.end_date}
          {...register(`legs.${legIndex}.end_date` as Path<T>)}
        />
        {errors?.end_date && (
          <p className="text-sm text-destructive">{errors.end_date.message}</p>
        )}
      </div>
    </div>
  );
}

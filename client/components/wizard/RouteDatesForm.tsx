"use client";

import { useFieldArray, useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";

import { LegRouteFields, legRouteFieldsSchema } from "@/components/legs/LegRouteFields";
import { Button } from "@/components/ui/button";
import { useBulkCreateLegs } from "@/hooks/use-trips";
import { ApiError } from "@/lib/api-client";
import type { LegBulkCreateIn, LegOut } from "@/lib/types";

const formSchema = z.object({
  legs: z.array(legRouteFieldsSchema).min(1, "Add at least one leg"),
});

type FormValues = z.infer<typeof formSchema>;

const emptyLegRow: FormValues["legs"][number] = {
  origin: "",
  destination: "",
  start_date: "",
  end_date: "",
};

interface RouteDatesFormProps {
  tripId: string;
  /** Next sequence_index to assign (0 on an empty trip; max existing + 1 otherwise). */
  nextSequenceIndex: number;
  onCreated: (legs: LegOut[]) => void;
}

export function RouteDatesForm({
  tripId,
  nextSequenceIndex,
  onCreated,
}: RouteDatesFormProps) {
  const bulkCreate = useBulkCreateLegs(tripId);

  const {
    register,
    control,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      legs: [emptyLegRow],
    },
  });

  const { fields, append, remove } = useFieldArray({ control, name: "legs" });

  async function onSubmit(values: FormValues) {
    const body: LegBulkCreateIn = {
      legs: values.legs.map((leg, index) => ({
        sequence_index: nextSequenceIndex + index,
        origin: leg.origin.trim(),
        destination: leg.destination.trim(),
        start_date: leg.start_date,
        end_date: leg.end_date,
      })),
    };

    try {
      const created = await bulkCreate.mutateAsync(body);
      onCreated(created);
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "Could not create legs. Try again."
      );
    }
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-6">
      <ul className="flex flex-col gap-4">
        {fields.map((field, index) => (
          <li
            key={field.id}
            className="flex flex-col gap-3 rounded-card border border-border-soft bg-bg p-4 shadow-card"
          >
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-xs font-bold tracking-[0.14em] text-ink uppercase">
                Leg {index + 1}
              </h2>
              {fields.length > 1 && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => remove(index)}
                >
                  Remove
                </Button>
              )}
            </div>

            <LegRouteFields
              legIndex={index}
              register={register}
              errors={errors.legs?.[index]}
            />
          </li>
        ))}
      </ul>

      {errors.legs?.root && (
        <p className="text-sm text-destructive">{errors.legs.root.message}</p>
      )}
      {typeof errors.legs?.message === "string" && (
        <p className="text-sm text-destructive">{errors.legs.message}</p>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <Button type="button" variant="outline" onClick={() => append(emptyLegRow)}>
          Add leg
        </Button>
        <Button type="submit" disabled={isSubmitting || bulkCreate.isPending}>
          {isSubmitting || bulkCreate.isPending ? "Saving…" : "Continue"}
        </Button>
      </div>
    </form>
  );
}

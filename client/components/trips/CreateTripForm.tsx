"use client";

import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiFetch, ApiError } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";
import type { TripCreateIn, TripOut } from "@/lib/types";

const createTripSchema = z.object({
  name: z.string().min(1, "Name is required"),
  home_currency: z
    .string()
    .regex(/^[A-Z]{3}$/, "Enter a 3-letter ISO 4217 code (e.g. USD)"),
  budget_band: z.enum(["budget", "comfort", "premium"]),
  budget_target_amount: z.string().optional(),
});

type CreateTripFormValues = z.infer<typeof createTripSchema>;

export function CreateTripForm() {
  const router = useRouter();
  const { accessToken } = useAuth();
  const {
    register,
    handleSubmit,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<CreateTripFormValues>({
    resolver: zodResolver(createTripSchema),
    defaultValues: {
      name: "",
      home_currency: "",
      budget_band: "comfort",
      budget_target_amount: "",
    },
  });

  async function onSubmit(values: CreateTripFormValues) {
    const trimmedTarget = values.budget_target_amount?.trim() ?? "";
    const body: TripCreateIn = {
      name: values.name,
      home_currency: values.home_currency,
      budget_band: values.budget_band,
      budget_target_amount: trimmedTarget === "" ? null : Number(trimmedTarget),
    };

    if (body.budget_target_amount !== null && Number.isNaN(body.budget_target_amount)) {
      toast.error("Budget target must be a number.");
      return;
    }

    try {
      const trip = await apiFetch<TripOut>("/trips", {
        method: "POST",
        body,
        token: accessToken,
      });
      router.push(`/trips/${trip.id}`);
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Something went wrong. Please try again.";
      toast.error(message);
    }
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="name">Trip name</Label>
        <Input
          id="name"
          placeholder="Southeast Asia 2026"
          aria-invalid={!!errors.name}
          {...register("name")}
        />
        {errors.name && <p className="text-sm text-destructive">{errors.name.message}</p>}
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

      <div className="flex flex-col gap-1.5">
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
          <p className="text-sm text-destructive">{errors.budget_target_amount.message}</p>
        )}
      </div>

      <Button type="submit" disabled={isSubmitting} className="w-full">
        {isSubmitting ? "Creating…" : "Create trip"}
      </Button>
    </form>
  );
}

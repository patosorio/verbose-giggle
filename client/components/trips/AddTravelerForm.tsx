"use client";

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAddTraveler } from "@/hooks/use-trips";
import { ApiError } from "@/lib/api-client";
import { cn } from "@/lib/utils";

const addTravelerSchema = z.object({
  name: z.string().min(1, "Name is required"),
  age_category: z.enum(["adult", "child"]),
});

type AddTravelerFormValues = z.infer<typeof addTravelerSchema>;

interface AddTravelerFormProps {
  tripId: string;
  /** "dark" for CrewCard (turquoise); "light" for wizard / light backgrounds. */
  variant?: "light" | "dark";
}

export function AddTravelerForm({ tripId, variant = "dark" }: AddTravelerFormProps) {
  const addTraveler = useAddTraveler(tripId);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<AddTravelerFormValues>({
    resolver: zodResolver(addTravelerSchema),
    defaultValues: {
      name: "",
      age_category: "adult",
    },
  });

  async function onSubmit(values: AddTravelerFormValues) {
    try {
      await addTraveler.mutateAsync(values);
      reset({ name: "", age_category: "adult" });
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Something went wrong. Please try again.";
      toast.error(message);
    }
  }

  const isDark = variant === "dark";

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="relative mt-4 flex flex-col gap-3">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="traveler-name" className={cn(isDark && "text-white")}>
          Name
        </Label>
        <Input
          id="traveler-name"
          placeholder="Alex"
          aria-invalid={!!errors.name}
          {...register("name")}
        />
        {errors.name && (
          <p className={cn("text-sm", isDark ? "text-white/90" : "text-destructive")}>
            {errors.name.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label
          htmlFor="traveler-age-category"
          className={cn(isDark && "text-white")}
        >
          Age category
        </Label>
        <select
          id="traveler-age-category"
          className="h-8 w-full rounded-lg border border-border bg-background px-2.5 text-sm text-ink outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          aria-invalid={!!errors.age_category}
          {...register("age_category")}
        >
          <option value="adult">Adult</option>
          <option value="child">Child</option>
        </select>
        {errors.age_category && (
          <p className={cn("text-sm", isDark ? "text-white/90" : "text-destructive")}>
            {errors.age_category.message}
          </p>
        )}
      </div>

      <Button type="submit" disabled={addTraveler.isPending} className="w-full">
        {addTraveler.isPending ? "Adding…" : "Add traveler"}
      </Button>
    </form>
  );
}

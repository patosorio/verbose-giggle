"use client";

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useCreateManualOption } from "@/hooks/use-options";
import { ApiError } from "@/lib/api-client";
import {
  MANUAL_TAB_CATEGORIES,
  MANUAL_TAB_CATEGORY_LABEL,
  type ManualTabCategory,
} from "@/lib/manual-option-category";
import type { ManualOptionIn } from "@/lib/types";

const manualOptionSchema = z
  .object({
    category: z.enum(MANUAL_TAB_CATEGORIES),
    tier: z.enum(["budget", "comfort", "premium"]),
    title: z.string().trim().min(1, "Title is required"),
    description: z.string().optional(),
    price_amount: z.string().optional(),
    price_currency: z.string().optional(),
  })
  .refine(
    (data) => {
      const hasAmount = (data.price_amount?.trim() ?? "") !== "";
      if (!hasAmount) return true;
      return (data.price_currency?.trim() ?? "") !== "";
    },
    {
      message: "Currency is required when a price is set",
      path: ["price_currency"],
    }
  )
  .superRefine((data, ctx) => {
    const currency = data.price_currency?.trim() ?? "";
    if (currency === "") return;
    if (!/^[A-Za-z]{3}$/.test(currency)) {
      ctx.addIssue({
        code: "custom",
        message: "Enter a 3-letter ISO currency code",
        path: ["price_currency"],
      });
    }
  });

type ManualOptionFormValues = z.infer<typeof manualOptionSchema>;

interface AddManualOptionFormProps {
  legId: string;
  homeCurrency: string;
  /** Prefill from the tab the user was viewing (e.g. Hotels → hotel). */
  defaultCategory?: ManualTabCategory;
  onSuccess: (category: ManualTabCategory) => void;
}

export function AddManualOptionForm({
  legId,
  homeCurrency,
  defaultCategory = "hotel",
  onSuccess,
}: AddManualOptionFormProps) {
  const createManual = useCreateManualOption(legId);
  const {
    register,
    handleSubmit,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<ManualOptionFormValues>({
    resolver: zodResolver(manualOptionSchema),
    defaultValues: {
      category: defaultCategory,
      tier: "comfort",
      title: "",
      description: "",
      price_amount: "",
      price_currency: homeCurrency,
    },
  });

  async function onSubmit(values: ManualOptionFormValues) {
    const trimmedAmount = values.price_amount?.trim() ?? "";
    const trimmedCurrency = values.price_currency?.trim().toUpperCase() ?? "";
    const hasPrice = trimmedAmount !== "";

    if (hasPrice && Number.isNaN(Number(trimmedAmount))) {
      toast.error("Price must be a number.");
      return;
    }

    const body: ManualOptionIn = {
      tier: values.tier,
      title: values.title.trim(),
      description: values.description?.trim() ? values.description.trim() : null,
      // Persisted as category_hint — drives which typed tab shows this imported card.
      category_hint: values.category,
      price_amount: hasPrice ? Number(trimmedAmount) : null,
      price_currency: hasPrice ? trimmedCurrency : null,
    };

    try {
      await createManual.mutateAsync(body);
      toast.success("Option added.");
      onSuccess(values.category);
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "Could not add this option."
      );
    }
  }

  const pending = isSubmitting || createManual.isPending;

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="manual-category">Type</Label>
        <select
          id="manual-category"
          className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          aria-invalid={!!errors.category}
          {...register("category")}
        >
          {MANUAL_TAB_CATEGORIES.map((category) => (
            <option key={category} value={category}>
              {MANUAL_TAB_CATEGORY_LABEL[category]}
            </option>
          ))}
        </select>
        {errors.category && (
          <p className="text-sm text-destructive">{errors.category.message}</p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="manual-tier">Tier</Label>
        <select
          id="manual-tier"
          className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          aria-invalid={!!errors.tier}
          {...register("tier")}
        >
          <option value="budget">Budget</option>
          <option value="comfort">Comfort</option>
          <option value="premium">Premium</option>
        </select>
        {errors.tier && <p className="text-sm text-destructive">{errors.tier.message}</p>}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="manual-title">Title</Label>
        <Input
          id="manual-title"
          placeholder="Phuket Airport private transfer"
          aria-invalid={!!errors.title}
          {...register("title")}
        />
        {errors.title && <p className="text-sm text-destructive">{errors.title.message}</p>}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="manual-description">Description (optional)</Label>
        <textarea
          id="manual-description"
          rows={3}
          placeholder="Driver name, pickup notes…"
          aria-invalid={!!errors.description}
          className="w-full min-w-0 rounded-lg border border-input bg-transparent px-2.5 py-1.5 text-sm outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          {...register("description")}
        />
        {errors.description && (
          <p className="text-sm text-destructive">{errors.description.message}</p>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="manual-price-amount">Price (optional)</Label>
          <Input
            id="manual-price-amount"
            type="number"
            step="any"
            min="0"
            placeholder="1200"
            aria-invalid={!!errors.price_amount}
            {...register("price_amount")}
          />
          {errors.price_amount && (
            <p className="text-sm text-destructive">{errors.price_amount.message}</p>
          )}
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="manual-price-currency">Currency</Label>
          <Input
            id="manual-price-currency"
            placeholder="USD"
            maxLength={3}
            aria-invalid={!!errors.price_currency}
            {...register("price_currency", {
              onBlur: (event) => {
                setValue("price_currency", event.target.value.trim().toUpperCase(), {
                  shouldValidate: true,
                });
              },
            })}
          />
          {errors.price_currency && (
            <p className="text-sm text-destructive">{errors.price_currency.message}</p>
          )}
        </div>
      </div>

      <Button type="submit" disabled={pending} className="w-full">
        {pending ? "Adding…" : "Add option"}
      </Button>
    </form>
  );
}

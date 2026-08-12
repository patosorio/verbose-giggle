"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiFetch, ApiError } from "@/lib/api-client";

const magicLinkSchema = z.object({
  email: z.string().min(1, "Email is required").email("Enter a valid email address"),
});

type MagicLinkFormValues = z.infer<typeof magicLinkSchema>;

export function MagicLinkRequestForm() {
  const [submitted, setSubmitted] = useState(false);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<MagicLinkFormValues>({
    resolver: zodResolver(magicLinkSchema),
    defaultValues: { email: "" },
  });

  async function onSubmit(values: MagicLinkFormValues) {
    try {
      await apiFetch<{ message: string }>("/auth/magic-link/request", {
        method: "POST",
        body: values,
      });
      setSubmitted(true);
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Something went wrong. Please try again.";
      toast.error(message);
    }
  }

  if (submitted) {
    return (
      <div className="rounded-md border border-border bg-muted/50 p-4 text-center">
        <p className="text-sm font-medium text-foreground">Check your email</p>
        <p className="mt-1 text-sm text-muted-foreground">
          If that address has an account, a magic link is on its way.
        </p>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="email">Email</Label>
        <Input
          id="email"
          type="email"
          autoComplete="email"
          placeholder="you@example.com"
          aria-invalid={!!errors.email}
          {...register("email")}
        />
        {errors.email && <p className="text-sm text-destructive">{errors.email.message}</p>}
      </div>
      <Button type="submit" disabled={isSubmitting} className="w-full">
        {isSubmitting ? "Sending…" : "Send magic link"}
      </Button>
    </form>
  );
}

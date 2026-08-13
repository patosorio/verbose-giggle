"use client";

import { useState } from "react";
import Link from "next/link";

import { AiTripPlanner } from "@/components/trips/AiTripPlanner";
import { ManualTripPlanner } from "@/components/trips/ManualTripPlanner";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type NewTripMode = "manual" | "ai";

export default function NewTripPage() {
  const [mode, setMode] = useState<NewTripMode>("manual");

  return (
    <div
      className={cn(
        "mx-auto flex w-full flex-col gap-6 p-6",
        mode === "manual" ? "max-w-3xl" : "max-w-6xl"
      )}
    >
      <div className="flex flex-col gap-2">
        <Link
          href="/trips"
          className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "w-fit px-0")}
        >
          ← Back to trips
        </Link>
        <h1 className="font-display text-2xl font-bold text-ink">New trip</h1>
        <p className="text-sm text-ink-muted">
          Chat with the advisor, or fill in the details yourself — either way you&apos;ll confirm before anything&apos;s booked.
        </p>
      </div>

      <div
        className="inline-flex w-fit rounded-[999px] border border-border-interactive p-1"
        role="tablist"
        aria-label="New trip mode"
      >
        <button
          type="button"
          role="tab"
          aria-selected={mode === "manual"}
          className={cn(
            "rounded-[999px] px-4 py-1.5 text-sm font-medium transition-colors",
            mode === "manual"
              ? "bg-[var(--turquoise)] text-white"
              : "text-ink-muted hover:text-ink"
          )}
          onClick={() => setMode("manual")}
        >
          Enter manually
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === "ai"}
          className={cn(
            "rounded-[999px] px-4 py-1.5 text-sm font-medium transition-colors",
            mode === "ai"
              ? "bg-[var(--turquoise)] text-white"
              : "text-ink-muted hover:text-ink"
          )}
          onClick={() => setMode("ai")}
        >
          Plan with AI
        </button>
      </div>

      {mode === "manual" ? <ManualTripPlanner /> : <AiTripPlanner />}
    </div>
  );
}

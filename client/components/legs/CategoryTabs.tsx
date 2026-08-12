"use client";

import type { OptionType } from "@/lib/types";
import { cn } from "@/lib/utils";

export const OPTION_TYPE_ORDER: OptionType[] = [
  "hotel",
  "flight",
  "activity",
  "transport",
  "imported",
];

export const OPTION_TYPE_LABEL: Record<OptionType, string> = {
  hotel: "Hotels",
  flight: "Flights",
  activity: "Activities",
  transport: "Transport",
  imported: "Imported",
};

interface CategoryTabsProps {
  presentTypes: OptionType[];
  activeType: OptionType | null;
  onChange: (type: OptionType) => void;
  /** When true, show the Imported tab (only for uncategorized URL/manual leftovers). */
  showImportedTab?: boolean;
}

// Hotels/Flights/Activities/Transport are a fixed, stable tab set regardless of
// whether this leg has options yet — the bar can't tell "not researched" apart
// from "researched, nothing found," so it doesn't reshape leg to leg (reverses
// the "hide empty tabs" behavior from docs/15_phase6_cursor_prompts.md Prompt 3).
// "Imported" stays conditional: categorized manuals live under typed tabs via
// category_hint; this slot is only for leftovers without a typed hint.
export function CategoryTabs({
  presentTypes,
  activeType,
  onChange,
  showImportedTab = false,
}: CategoryTabsProps) {
  const tabs = OPTION_TYPE_ORDER.filter((type) => {
    if (type === "imported") {
      return showImportedTab && presentTypes.includes("imported");
    }
    return true;
  });

  return (
    <div className="flex flex-wrap gap-2" role="tablist" aria-label="Option categories">
      {tabs.map((type) => {
        const isActive = type === activeType;
        return (
          <button
            key={type}
            type="button"
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(type)}
            className={cn(
              "rounded-pill px-4 py-1.5 text-sm font-medium transition-[filter] hover:brightness-[1.08]",
              isActive
                ? "bg-turquoise text-white"
                : "bg-surface-alt text-ink border border-border-interactive"
            )}
          >
            {OPTION_TYPE_LABEL[type]}
          </button>
        );
      })}
    </div>
  );
}

import type { ImportedOptionOut, OptionCardOut, OptionType } from "@/lib/types";

/** Values stored in ImportedOption.category_hint for manual "add your own" entries. */
export const MANUAL_TAB_CATEGORIES = [
  "hotel",
  "flight",
  "activity",
  "transport",
] as const;

export type ManualTabCategory = (typeof MANUAL_TAB_CATEGORIES)[number];

export const MANUAL_TAB_CATEGORY_LABEL: Record<ManualTabCategory, string> = {
  hotel: "Hotel",
  flight: "Flight",
  activity: "Activity",
  transport: "Transport",
};

export function isManualTabCategory(value: string | null | undefined): value is ManualTabCategory {
  return (
    value !== null &&
    value !== undefined &&
    (MANUAL_TAB_CATEGORIES as readonly string[]).includes(value)
  );
}

/** Imported options whose category_hint matches a typed tab live under that tab. */
export function importedMatchesTab(
  option: ImportedOptionOut,
  tab: Exclude<OptionType, "imported">
): boolean {
  return option.category_hint === tab;
}

/** Imported options with no typed category_hint still need the Imported tab. */
export function isUncategorizedImported(option: OptionCardOut): boolean {
  return (
    option.option_type === "imported" && !isManualTabCategory(option.category_hint)
  );
}

export function optionBelongsToTab(option: OptionCardOut, tab: OptionType): boolean {
  if (tab === "imported") {
    return isUncategorizedImported(option);
  }
  if (option.option_type === tab) {
    return true;
  }
  return (
    option.option_type === "imported" &&
    importedMatchesTab(option, tab)
  );
}

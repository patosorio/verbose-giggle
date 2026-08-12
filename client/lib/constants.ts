/** Shared brand accent cycle — docs/07_design_spec.md §2/§5. Used anywhere a set of
 * legs/stops/travelers needs to cycle through the 4-accent set (route strip arrows,
 * nav avatar stack, etc.) so every surface cycles in the same order. */

export const ACCENT_COLORS = ["coral-pink", "turquoise", "sunshine", "deep-ocean"] as const;

export type AccentColor = (typeof ACCENT_COLORS)[number];

export const ACCENT_FILL_CLASSES: Record<AccentColor, string> = {
  "coral-pink": "bg-coral-pink text-white",
  turquoise: "bg-turquoise text-white",
  sunshine: "bg-sunshine text-ink",
  "deep-ocean": "bg-deep-ocean text-white",
};

export const ACCENT_TEXT_CLASSES: Record<AccentColor, string> = {
  "coral-pink": "text-coral-pink",
  turquoise: "text-turquoise",
  sunshine: "text-sunshine",
  "deep-ocean": "text-deep-ocean",
};

export function accentAt(index: number): AccentColor {
  return ACCENT_COLORS[index % ACCENT_COLORS.length];
}

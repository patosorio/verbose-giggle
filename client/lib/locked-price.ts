import { formatCurrency } from "@/lib/format";
import type { LockedOptionSummaryOut, OptionType } from "@/lib/types";

export type PriceBreakdown = {
  unit: string;
  qtyLabel: string;
  total: string;
  /** Numeric full line total (party/stay), for section sums. */
  totalAmount: number;
};

export type LockedPriceBreakdownOptions = {
  nights?: number;
};

/** Full budget line total — party total for activity/transport, stay total for hotel. */
export function lockedLineTotalAmount(
  option: LockedOptionSummaryOut,
  options: LockedPriceBreakdownOptions = {}
): number {
  if (
    (option.option_type === "activity" || option.option_type === "transport") &&
    option.unit_price_amount !== null &&
    option.party_size !== null
  ) {
    const unit = Number(option.unit_price_amount);
    const party = option.party_size;
    if (Number.isFinite(unit) && party > 0) {
      return unit * party;
    }
  }

  const amount = Number(option.amount);
  return Number.isFinite(amount) ? amount : 0;
}

/** Unit × qty = total columns for locked summary rows. */
export function lockedPriceBreakdown(
  option: LockedOptionSummaryOut,
  options: LockedPriceBreakdownOptions = {}
): PriceBreakdown | null {
  const nights = options.nights;
  if (
    (option.option_type === "activity" || option.option_type === "transport") &&
    option.unit_price_amount !== null &&
    option.party_size !== null
  ) {
    const unit = Number(option.unit_price_amount);
    const party = option.party_size;
    if (!Number.isFinite(unit) || party <= 0) {
      return null;
    }
    const total = unit * party;
    return {
      unit: formatCurrency(option.unit_price_amount, option.currency),
      qtyLabel: `${party} ${party === 1 ? "person" : "people"}`,
      total: formatCurrency(String(total), option.currency),
      totalAmount: total,
    };
  }

  if (option.option_type === "hotel") {
    const stay = Number(option.amount);
    if (!Number.isFinite(stay)) {
      return null;
    }
    const nightCount = nights !== undefined && nights > 0 ? nights : 1;
    const nightly = stay / nightCount;
    return {
      unit: formatCurrency(String(nightly), option.currency),
      qtyLabel: `${nightCount} ${nightCount === 1 ? "night" : "nights"}`,
      total: formatCurrency(option.amount, option.currency),
      totalAmount: stay,
    };
  }

  return null;
}

export function sectionUnitHeader(type: OptionType): string | null {
  switch (type) {
    case "activity":
    case "transport":
      return "Per person";
    case "hotel":
      return "Per night";
    default:
      return null;
  }
}

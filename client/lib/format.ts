import type { TravelerOut } from "@/lib/types";

export function formatCurrency(amount: string, currency: string): string {
  const numeric = Number(amount);
  if (Number.isNaN(numeric)) {
    return `${currency} ${amount}`;
  }
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency,
      maximumFractionDigits: 0,
    }).format(numeric);
  } catch {
    return `${currency} ${amount}`;
  }
}

export function formatPartySize(travelers: TravelerOut[]): string {
  const adults = travelers.filter((t) => t.age_category === "adult").length;
  const children = travelers.filter((t) => t.age_category === "child").length;

  if (adults === 0 && children === 0) {
    return "No travelers yet";
  }

  const adultLabel = adults === 1 ? "1 adult" : `${adults} adults`;
  if (children === 0) {
    return adultLabel;
  }
  const childLabel = children === 1 ? "1 child" : `${children} children`;
  return `${adultLabel} + ${childLabel}`;
}

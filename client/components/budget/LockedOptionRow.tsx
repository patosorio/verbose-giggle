"use client";

import { useState } from "react";

import { useOptionCitations, useOptionSources } from "@/hooks/use-options";
import { formatCurrency } from "@/lib/format";
import {
  lockedPriceBreakdown,
} from "@/lib/locked-price";
import type { LockedOptionSummaryOut, OptionType } from "@/lib/types";

type SectionEntry = {
  legId: string;
  routeLabel: string;
  nights: number;
  option: LockedOptionSummaryOut;
};

function PriceColumns({
  breakdown,
}: {
  breakdown: NonNullable<ReturnType<typeof lockedPriceBreakdown>>;
}) {
  return (
    <div className="grid shrink-0 grid-cols-[minmax(5.5rem,auto)_minmax(4.5rem,auto)_minmax(5.5rem,auto)] items-baseline gap-x-3 text-right text-sm">
      <span className="font-medium text-ink">{breakdown.unit}</span>
      <span className="text-ink-muted">× {breakdown.qtyLabel}</span>
      <span className="font-bold text-ink">{breakdown.total}</span>
    </div>
  );
}

export function LockedOptionRow({
  entry,
  type,
}: {
  entry: SectionEntry;
  type: OptionType;
}) {
  const { routeLabel, nights, option } = entry;
  const [expanded, setExpanded] = useState(false);
  const breakdown = lockedPriceBreakdown(option, { nights });
  const showThumb = type === "hotel";

  return (
    <li className="flex flex-col gap-2 py-3">
      <button
        type="button"
        className="flex w-full flex-col gap-2 text-left sm:grid sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center sm:gap-4"
        onClick={() => setExpanded((open) => !open)}
        aria-expanded={expanded}
      >
        <div className="flex min-w-0 items-start gap-3">
          {showThumb ? (
            <HotelThumb url={option.thumbnail_url} />
          ) : null}
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="truncate text-sm font-medium text-ink">{option.title}</span>
            <span className="text-xs text-ink-muted">{routeLabel}</span>
            {option.room_label ? (
              <span className="text-xs text-ink-muted">{option.room_label}</span>
            ) : null}
          </div>
        </div>
        {breakdown ? (
          <PriceColumns breakdown={breakdown} />
        ) : (
          <span className="shrink-0 text-right text-sm font-bold text-ink">
            {formatCurrency(option.amount, option.currency)}
          </span>
        )}
      </button>
      {expanded ? <LockedRowExpand option={option} type={type} /> : null}
    </li>
  );
}

function HotelThumb({ url }: { url: string | null | undefined }) {
  return (
    <div className="h-14 w-[72px] shrink-0 overflow-hidden rounded-chip bg-surface-alt">
          {url ? (
            <img src={url} alt="" className="h-full w-full object-cover" />
          ) : null}
    </div>
  );
}

function LockedRowExpand({
  option,
  type,
}: {
  option: LockedOptionSummaryOut;
  type: OptionType;
}) {
  if (type === "hotel") {
    return <HotelExpand option={option} />;
  }
  if (type === "activity") {
    return <ActivityExpand option={option} />;
  }
  if (type === "flight") {
    return (
      <dl className="grid gap-1 pl-[84px] text-sm text-ink-muted sm:pl-0">
        {option.departure_airport && option.arrival_airport ? (
          <div>
            {option.departure_airport} → {option.arrival_airport}
            {option.stops != null ? ` · ${option.stops} stop${option.stops === 1 ? "" : "s"}` : ""}
          </div>
        ) : null}
        {option.airlines && option.airlines.length > 0 ? (
          <div>{option.airlines.join(", ")}</div>
        ) : null}
        {option.duration_minutes != null ? <div>{option.duration_minutes} min</div> : null}
        {option.bags_included ? <div>Bags included</div> : null}
      </dl>
    );
  }
  if (type === "transport") {
    return (
      <dl className="grid gap-1 text-sm text-ink-muted">
        {option.mode ? <div className="capitalize">{option.mode.replaceAll("_", " ")}</div> : null}
        {option.operator_name ? <div>{option.operator_name}</div> : null}
        {option.departure_point && option.arrival_point ? (
          <div>
            {option.departure_point} → {option.arrival_point}
          </div>
        ) : null}
        {option.duration_minutes != null ? <div>{option.duration_minutes} min</div> : null}
        {option.booking_url ? (
          <a
            href={option.booking_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-turquoise underline underline-offset-2"
          >
            Booking link
          </a>
        ) : null}
      </dl>
    );
  }
  return null;
}

function HotelExpand({ option }: { option: LockedOptionSummaryOut }) {
  const detailsQuery = useOptionSources(option.option_card_id, true);
  const details = detailsQuery.data?.hotel_details;
  return (
    <div className="flex flex-col gap-2 pl-[84px] text-sm text-ink-muted sm:pl-0">
      {option.star_rating ? <div>{option.star_rating}★</div> : null}
      {option.checkin_date && option.checkout_date ? (
        <div>
          {option.checkin_date} → {option.checkout_date}
        </div>
      ) : null}
      {option.amenities && option.amenities.length > 0 ? (
        <div>{option.amenities.join(" · ")}</div>
      ) : null}
      {detailsQuery.isLoading ? <p>Loading details…</p> : null}
      {details?.description ? <p className="text-ink">{details.description}</p> : null}
      {details && details.image_thumbnails.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {details.image_thumbnails.slice(0, 8).map((src) => (
            <img
              key={src}
              src={src}
              alt=""
              className="h-16 w-20 rounded-chip object-cover bg-surface-alt"
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ActivityExpand({ option }: { option: LockedOptionSummaryOut }) {
  const citationsQuery = useOptionCitations(option.option_card_id, true);
  return (
    <div className="flex flex-col gap-2 text-sm text-ink-muted">
      {option.category ? <div>{option.category}</div> : null}
      {option.duration_minutes != null ? <div>{option.duration_minutes} min</div> : null}
      {option.description ? <p className="text-ink">{option.description}</p> : null}
      {citationsQuery.isLoading ? <p>Loading citations…</p> : null}
      {citationsQuery.data && citationsQuery.data.length > 0 ? (
        <ul className="flex flex-col gap-1">
          {citationsQuery.data.map((citation, index) => (
            <li key={index}>
              <a
                href={citation.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-turquoise underline underline-offset-2"
              >
                {citation.claim_text}
              </a>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

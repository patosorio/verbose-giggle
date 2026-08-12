"use client";

import { useState, type KeyboardEvent, type MouseEvent } from "react";
import { useParams } from "next/navigation";

import { PopoverContent, Popover, PopoverTrigger } from "@/components/ui/popover";
import { useOptionCitations, useOptionSources, useRemoveReaction, useSetReaction } from "@/hooks/use-options";
import { formatCurrency } from "@/lib/format";
import type { BookingSourceOut, CitationOut, OptionCardOut, OptionType, ReactionType } from "@/lib/types";
import { cn } from "@/lib/utils";

function formatDuration(minutes: number): string {
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  if (hours === 0) return `${mins}m`;
  if (mins === 0) return `${hours}h`;
  return `${hours}h ${mins}m`;
}

function formatStops(stops: number): string {
  if (stops === 0) return "Nonstop";
  if (stops === 1) return "1 stop";
  return `${stops} stops`;
}

function formatMode(mode: string): string {
  return mode.replaceAll("_", " ");
}

export function metaLine(option: OptionCardOut): string {
  switch (option.option_type) {
    case "flight":
      return `${formatStops(option.stops)} · ${formatDuration(option.duration_minutes)}`;
    case "hotel": {
      // Eco-certified is the more distinctive fact when true; cancellation policy
      // is the fallback. Mockup's meta line is always exactly one fact after the
      // star rating, never both.
      const fact = option.eco_certified
        ? "Eco-certified"
        : option.free_cancellation
          ? "Free cancellation"
          : "Non-refundable";
      const base = `${option.star_rating}★ · ${fact}`;
      return option.room_label ? `${base} · ${option.room_label}` : base;
    }
    case "activity":
      return option.category;
    case "transport": {
      const mode = formatMode(option.mode);
      return option.operator_name ? `${mode} · ${option.operator_name}` : mode;
    }
    case "imported":
      return option.category_hint ?? "Imported";
  }
}

export interface PriceLine {
  main: string;
  suffix?: string;
  /** Activity/transport: unit × party = total, once partySize is known. */
  breakdown?: string;
}

/** Context for research-table unit rates (budget/lock still use stored totals). */
export interface PriceLineContext {
  /** Leg nights — hotel SerpApi total_rate ÷ nights → /night display. */
  nights?: number;
  /** Occupancy party size — activity/transport unit × total breakdown. */
  partySize?: number;
}

export function priceLine(
  option: OptionCardOut,
  context: PriceLineContext = {}
): PriceLine {
  if (option.base_price_amount === null) {
    return { main: "Price not listed" };
  }

  const raw = Number(option.base_price_amount);
  if (Number.isNaN(raw)) {
    return { main: `Priced in ${option.currency}` };
  }

  // Hotels: SerpApi stores total_rate for the whole stay (searched party). Research
  // shows the nightly equivalent; budget/lock still use the stay total.
  if (option.option_type === "hotel") {
    const nights = context.nights !== undefined && context.nights > 0 ? context.nights : 1;
    const nightly = raw / nights;
    return {
      main: formatCurrency(String(nightly), option.currency),
      suffix: "/night · party",
    };
  }

  if (option.option_type === "activity" || option.option_type === "transport") {
    const partySize =
      context.partySize !== undefined && context.partySize > 0 ? context.partySize : 1;
    const total = raw * partySize;
    const originalNote =
      option.original_price_amount !== null && option.original_currency !== null
        ? ` · from ${formatCurrency(option.original_price_amount, option.original_currency)}`
        : "";
    return {
      main: formatCurrency(option.base_price_amount, option.currency),
      suffix: `/person${originalNote}`,
      breakdown: `${formatCurrency(option.base_price_amount, option.currency)} × ${partySize} = ${formatCurrency(String(total), option.currency)}`,
    };
  }

  // Flights (and imported without a typed unit): one-shot amount as stored.
  return { main: formatCurrency(option.base_price_amount, option.currency) };
}

// "N sources" is one visual pattern over two different endpoints (docs/07_design_spec.md
// §5): flight/hotel back it with BookingSource rows, activity/transport with Citation rows.
// Imported options have neither (services/options.py 404s for both on that type), so the
// tag doesn't render at all there.
export type SourcesKind = "sources" | "citations";

export function sourcesKindFor(optionType: OptionType): SourcesKind | null {
  switch (optionType) {
    case "flight":
    case "hotel":
      return "sources";
    case "activity":
    case "transport":
      return "citations";
    case "imported":
      return null;
  }
}

const GRADIENT_BY_TYPE: Record<OptionType, string> = {
  flight: "from-turquoise/80 to-deep-ocean",
  hotel: "from-coral-pink/80 to-sunshine/70",
  activity: "from-sunshine/90 to-coral-pink/70",
  transport: "from-deep-ocean to-turquoise/70",
  imported: "from-ink-muted/40 to-surface-alt",
};

export function stop(handler: () => void) {
  return (event: MouseEvent) => {
    event.stopPropagation();
    handler();
  };
}

export interface ReactionButtonProps {
  active: boolean;
  pending: boolean;
  onToggle: () => void;
  emoji: string;
  label: string;
}

export function ReactionButton({ active, pending, onToggle, emoji, label }: ReactionButtonProps) {
  return (
    <button
      type="button"
      aria-pressed={active}
      aria-label={label}
      disabled={pending}
      onClick={stop(onToggle)}
      className={cn(
        "flex size-8 items-center justify-center rounded-full text-sm transition-transform hover:scale-[1.12] disabled:pointer-events-none disabled:opacity-60",
        active ? "bg-coral-pink/15" : "bg-surface-alt"
      )}
    >
      {emoji}
    </button>
  );
}

export function SourcesTag({ optionId, kind }: { optionId: string; kind: SourcesKind }) {
  const [hasOpened, setHasOpened] = useState(false);
  // Lazy: only fetched once the popover has actually been opened once (N cards per
  // leg means N extra requests if this were eager on page load).
  const sourcesQuery = useOptionSources(optionId, hasOpened && kind === "sources");
  const citationsQuery = useOptionCitations(optionId, hasOpened && kind === "citations");
  const query = kind === "sources" ? sourcesQuery : citationsQuery;
  const count = query.data?.length;

  return (
    <Popover onOpenChange={(open) => open && setHasOpened(true)}>
      <PopoverTrigger
        onClick={stop(() => {})}
        className="text-xs text-ink-muted transition-colors hover:text-ink hover:underline"
      >
        {count !== undefined ? `${count} source${count === 1 ? "" : "s"}` : "Sources"}
      </PopoverTrigger>
      <PopoverContent align="end" onClick={(event: MouseEvent) => event.stopPropagation()}>
        {query.isLoading ? (
          <p className="text-sm text-ink-muted">Loading…</p>
        ) : query.isError ? (
          <p className="text-sm text-destructive">Could not load {kind}.</p>
        ) : !query.data || query.data.length === 0 ? (
          <p className="text-sm text-ink-muted">No {kind} yet.</p>
        ) : kind === "sources" ? (
          <ul className="flex flex-col gap-3">
            {(query.data as BookingSourceOut[]).map((source, index) => (
              <li key={index} className="flex flex-col gap-0.5">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-sm font-semibold text-ink">{source.seller_name}</span>
                  <span className="text-sm font-bold text-ink">
                    {formatCurrency(source.price_amount, source.currency)}
                  </span>
                </div>
                <a
                  href={source.deep_link_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-turquoise underline underline-offset-2"
                >
                  View booking link
                </a>
              </li>
            ))}
          </ul>
        ) : (
          <ul className="flex flex-col gap-3">
            {(query.data as CitationOut[]).map((citation, index) => (
              <li key={index} className="flex flex-col gap-0.5">
                <p className="text-sm text-ink">{citation.claim_text}</p>
                <a
                  href={citation.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-turquoise underline underline-offset-2"
                >
                  Source
                </a>
              </li>
            ))}
          </ul>
        )}
      </PopoverContent>
    </Popover>
  );
}

interface OptionCardProps {
  option: OptionCardOut;
  isLocked: boolean;
  isSelected?: boolean;
  onSelect?: () => void;
  nights?: number;
  partySize?: number;
}

export function OptionCard({
  option,
  isLocked,
  isSelected = false,
  onSelect,
  nights,
  partySize,
}: OptionCardProps) {
  const { legId } = useParams<{ legId: string }>();
  const setReaction = useSetReaction(legId);
  const removeReaction = useRemoveReaction(legId);

  const { up, down, my_reaction } = option.reaction_summary;
  const price = priceLine(option, { nights, partySize });
  const sourcesKind = sourcesKindFor(option.option_type);
  const reactionPending = setReaction.isPending || removeReaction.isPending;

  function toggleReaction(type: ReactionType) {
    if (my_reaction === type) {
      removeReaction.mutate(option.id);
    } else {
      setReaction.mutate({ optionId: option.id, reactionType: type });
    }
  }

  function handleKeyDown(event: KeyboardEvent) {
    if (!onSelect) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelect();
    }
  }

  return (
    <article
      role={onSelect ? "button" : undefined}
      tabIndex={onSelect ? 0 : undefined}
      onClick={onSelect}
      onKeyDown={handleKeyDown}
      className={cn(
        "relative flex flex-col overflow-hidden rounded-card border border-border-soft bg-bg shadow-card transition-transform hover:-translate-y-0.5 hover:shadow-md",
        onSelect && "cursor-pointer",
        isLocked && "border-[3px] border-coral-pink shadow-[3px_3px_0_0_var(--coral-pink)]",
        !isLocked &&
          isSelected &&
          "border-[3px] border-sunshine shadow-[3px_3px_0_0_var(--sunshine)]"
      )}
    >
      {isLocked && (
        <span className="absolute top-2 right-2 z-10 rounded-pill bg-coral-pink px-2.5 py-0.5 text-[10px] font-bold tracking-wider text-white uppercase">
          Locked
        </span>
      )}
      {!isLocked && isSelected && (
        <span className="absolute top-2 right-2 z-10 rounded-pill bg-sunshine px-2.5 py-0.5 text-[10px] font-bold tracking-wider text-ink uppercase">
          Selected
        </span>
      )}

      <div
        className={cn(
          "h-28 w-full bg-linear-to-br",
          GRADIENT_BY_TYPE[option.option_type]
        )}
        aria-hidden
      />

      <div className="flex flex-col gap-2 p-3">
        <h3 className="font-heading text-[15px] leading-snug font-medium text-ink">
          {option.title}
        </h3>
        <p className="text-sm text-ink-muted">{metaLine(option)}</p>
        <p className="font-heading text-base font-bold text-ink">
          {price.main}
          {price.suffix && (
            <span className="text-xs font-normal text-ink-muted">{price.suffix}</span>
          )}
        </p>
        {price.breakdown && (
          <p className="text-xs text-ink-muted">{price.breakdown}</p>
        )}
        {option.option_type === "transport" && option.booking_url && (
          <a
            href={option.booking_url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={stop(() => {})}
            className="text-xs text-turquoise underline underline-offset-2"
          >
            Book directly →
          </a>
        )}

        <div className="mt-1.5 flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <ReactionButton
              active={my_reaction === "up"}
              pending={reactionPending}
              onToggle={() => toggleReaction("up")}
              emoji="👍"
              label="Thumbs up"
            />
            {up > 0 && (
              <span
                className={cn(
                  "text-xs font-bold",
                  my_reaction === "up" ? "text-coral-pink" : "text-ink-muted"
                )}
              >
                {up}
              </span>
            )}
            <ReactionButton
              active={my_reaction === "down"}
              pending={reactionPending}
              onToggle={() => toggleReaction("down")}
              emoji="👎"
              label="Thumbs down"
            />
            {down > 0 && (
              <span
                className={cn(
                  "text-xs font-bold",
                  my_reaction === "down" ? "text-coral-pink" : "text-ink-muted"
                )}
              >
                {down}
              </span>
            )}
          </div>
          {sourcesKind && <SourcesTag optionId={option.id} kind={sourcesKind} />}
          {option.option_type === "imported" && option.source_url && (
            <a
              href={option.source_url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={stop(() => {})}
              className="text-xs text-turquoise underline underline-offset-2"
            >
              View source
            </a>
          )}
        </div>
      </div>
    </article>
  );
}

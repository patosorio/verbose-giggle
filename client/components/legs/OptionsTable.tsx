"use client";

import { type KeyboardEvent } from "react";
import { useParams } from "next/navigation";

import {
  metaLine,
  priceLine,
  ReactionButton,
  SourcesTag,
  sourcesKindFor,
  stop,
} from "@/components/options/OptionCard";
import { useSetBooked } from "@/hooks/use-legs";
import { useRemoveReaction, useSetReaction } from "@/hooks/use-options";
import type { BudgetBand, OptionCardOut, ReactionType } from "@/lib/types";
import { cn } from "@/lib/utils";

const TIER_LABEL: Record<BudgetBand, string> = {
  budget: "Budget",
  comfort: "Comfort",
  premium: "Premium",
};

const TIER_DOT_CLASS: Record<BudgetBand, string> = {
  budget: "bg-turquoise",
  comfort: "bg-coral-pink",
  premium: "bg-sunshine",
};

const TIER_ORDER: Record<BudgetBand, number> = {
  budget: 0,
  comfort: 1,
  premium: 2,
};

function sortByTier(options: OptionCardOut[]): OptionCardOut[] {
  return [...options].sort((a, b) => {
    const aRank = a.tier === null ? 3 : TIER_ORDER[a.tier];
    const bRank = b.tier === null ? 3 : TIER_ORDER[b.tier];
    return aRank - bRank;
  });
}

interface OptionsTableProps {
  options: OptionCardOut[];
  lockedOptionIds: readonly string[];
  bookedByOptionId: Readonly<Record<string, boolean>>;
  selectedOptionId?: string | null;
  onSelectOption?: (optionId: string) => void;
  nights?: number;
  partySize?: number;
}

interface OptionRowProps {
  option: OptionCardOut;
  isLocked: boolean;
  isBooked: boolean;
  isSelected: boolean;
  onSelect?: () => void;
  nights?: number;
  partySize?: number;
}

function OptionRow({
  option,
  isLocked,
  isBooked,
  isSelected,
  onSelect,
  nights,
  partySize,
}: OptionRowProps) {
  const { tripId, legId } = useParams<{ tripId: string; legId: string }>();
  const setReaction = useSetReaction(legId);
  const removeReaction = useRemoveReaction(legId);
  const setBooked = useSetBooked(tripId, legId);

  const { up, down, my_reaction } = option.reaction_summary;
  const price = priceLine(option, { nights, partySize });
  const sourcesKind = sourcesKindFor(option.option_type);
  const reactionPending = setReaction.isPending || removeReaction.isPending;
  const bookedPending = setBooked.isPending;

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

  // Left accent must live on the first <td>, not the <tr> — border-collapse tables
  // don't paint left/right borders set on <tr> in most browsers.
  const accentClass = isLocked
    ? "border-l-4 border-l-coral-pink"
    : isSelected
      ? "border-l-4 border-l-sunshine"
      : "border-l-4 border-l-transparent";

  return (
    <tr
      role={onSelect ? "button" : undefined}
      tabIndex={onSelect ? 0 : undefined}
      onClick={onSelect}
      onKeyDown={handleKeyDown}
      className={cn(
        onSelect && "cursor-pointer",
        isLocked && "bg-coral-pink/5",
        !isLocked && isSelected && "bg-sunshine/10"
      )}
    >
      <td className={cn("px-3 py-3 align-middle", accentClass)}>
        {option.tier === null ? (
          <span className="text-sm text-ink-muted">—</span>
        ) : (
          <span className="flex items-center gap-2">
            <span
              className={cn("size-2.5 shrink-0 rounded-full", TIER_DOT_CLASS[option.tier])}
              aria-hidden
            />
            <span className="text-sm text-ink">{TIER_LABEL[option.tier]}</span>
          </span>
        )}
      </td>
      <td className="px-3 py-3 align-middle">
        <div className="flex flex-col gap-0.5">
          <span className="font-heading text-sm font-medium text-ink">{option.title}</span>
          {option.option_type === "imported" && (
            <span className="text-[10px] font-bold tracking-wider text-ink-muted uppercase">
              Added by you
            </span>
          )}
        </div>
      </td>
      <td className="px-3 py-3 align-middle text-sm text-ink-muted">{metaLine(option)}</td>
      <td className="px-3 py-3 text-right align-middle">
        <div className="flex flex-col items-end gap-0.5">
          <span className="font-heading text-sm font-bold text-ink">
            {price.main}
            {price.suffix && (
              <span className="text-xs font-normal text-ink-muted">{price.suffix}</span>
            )}
          </span>
          {price.breakdown && (
            <span className="text-xs text-ink-muted">{price.breakdown}</span>
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
        </div>
      </td>
      <td className="px-3 py-3 align-middle">
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
      </td>
      <td className="px-3 py-3 align-middle">
        {sourcesKind ? (
          <SourcesTag optionId={option.id} kind={sourcesKind} />
        ) : option.option_type === "imported" && option.source_url ? (
          <a
            href={option.source_url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={stop(() => {})}
            className="text-xs text-turquoise underline underline-offset-2"
          >
            View source
          </a>
        ) : (
          <span className="text-sm text-ink-muted">—</span>
        )}
      </td>
      <td className="px-3 py-3 text-right align-middle">
        {isLocked ? (
          <div className="flex flex-col items-end gap-1.5">
            <span className="rounded-pill bg-coral-pink px-2.5 py-0.5 text-[10px] font-bold tracking-wider text-white uppercase">
              Locked
            </span>
            <button
              type="button"
              aria-pressed={isBooked}
              aria-label={isBooked ? "Mark as not booked" : "Mark as booked"}
              disabled={bookedPending}
              onClick={stop(() =>
                setBooked.mutate({ optionCardId: option.id, isBooked: !isBooked })
              )}
              className={cn(
                "rounded-pill px-2.5 py-0.5 text-[10px] font-bold tracking-wider uppercase disabled:pointer-events-none disabled:opacity-60",
                isBooked
                  ? "bg-turquoise text-white"
                  : "border border-border-interactive bg-surface-alt text-ink"
              )}
            >
              {isBooked ? "Booked ✓" : "Mark booked"}
            </button>
          </div>
        ) : isSelected ? (
          <span className="rounded-pill bg-sunshine px-2.5 py-0.5 text-[10px] font-bold tracking-wider text-ink uppercase">
            Selected
          </span>
        ) : null}
      </td>
    </tr>
  );
}

export function OptionsTable({
  options,
  lockedOptionIds,
  bookedByOptionId,
  selectedOptionId = null,
  onSelectOption,
  nights,
  partySize,
}: OptionsTableProps) {
  const sorted = sortByTier(options);
  const lockedIds = new Set(lockedOptionIds);

  return (
    <div className="overflow-x-auto rounded-card border border-border-soft shadow-card">
      <table className="w-full min-w-[42rem] border-collapse text-left">
        <thead>
          <tr className="bg-surface-alt">
            {(
              ["Tier", "Option", "Details", "Price", "Reactions", "Sources", "Status"] as const
            ).map((label) => (
              <th
                key={label}
                className={cn(
                  "px-3 py-2.5 text-xs font-bold tracking-[0.14em] text-ink uppercase",
                  (label === "Price" || label === "Status") && "text-right"
                )}
              >
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((option) => (
            <OptionRow
              key={option.id}
              option={option}
              isLocked={lockedIds.has(option.id)}
              isBooked={bookedByOptionId[option.id] ?? false}
              isSelected={option.id === selectedOptionId}
              onSelect={onSelectOption ? () => onSelectOption(option.id) : undefined}
              nights={nights}
              partySize={partySize}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

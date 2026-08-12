"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState, type FormEvent, type ReactNode } from "react";
import { toast } from "sonner";

import { Button, buttonVariants } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useInviteMember, useTrip, useTripTravelers } from "@/hooks/use-trips";
import { ApiError } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";
import { ACCENT_FILL_CLASSES, accentAt } from "@/lib/constants";
import { formatPartySize } from "@/lib/format";
import { cn } from "@/lib/utils";

const MAX_VISIBLE_AVATARS = 3;

export function AppShell({ children }: { children: ReactNode }) {
  const { clearAuth, user } = useAuth();
  const router = useRouter();
  const params = useParams<{ tripId?: string }>();
  const tripId = params.tripId;

  const tripQuery = useTrip(tripId ?? "");
  const travelersQuery = useTripTravelers(tripId ?? "");
  const travelers = travelersQuery.data ?? [];
  const visibleTravelers = travelers.slice(0, MAX_VISIBLE_AVATARS);
  const overflowCount = travelers.length - visibleTravelers.length;

  const isOrganizer =
    !!user && !!tripQuery.data && user.id === tripQuery.data.organizer_id;

  const [inviteOpen, setInviteOpen] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const inviteMember = useInviteMember(tripId ?? "");

  function handleLogout() {
    clearAuth();
    router.push("/login");
  }

  async function handleInvite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!tripId) return;
    try {
      await inviteMember.mutateAsync({ email: inviteEmail.trim() });
      toast.success("Invite sent.");
      setInviteEmail("");
      setInviteOpen(false);
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "Could not invite this email."
      );
    }
  }

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <header className="shrink-0 flex flex-wrap items-center justify-between gap-4 border-b border-border-soft px-6 py-5 md:px-14 md:py-7">
        <Link
          href="/trips"
          className="flex items-center gap-3.5 rounded-chip outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          <div
            className="flex h-11 w-11 shrink-0 rotate-[-6deg] items-center justify-center rounded-chip bg-coral-pink"
            aria-hidden
          >
            <span className="font-display text-xl font-black text-white">T</span>
          </div>
          <span className="font-display text-[26px] font-black tracking-tight text-ink">
            Travel
          </span>
        </Link>

        {tripId && tripQuery.data && (
          <div className="flex items-center gap-2.5 text-[15px] font-normal text-ink">
            <span className="size-2 shrink-0 rounded-full bg-turquoise" aria-hidden />
            <span>
              {tripQuery.data.name} · {formatPartySize(travelers)}
            </span>
          </div>
        )}

        <div className="flex items-center gap-4">
          {tripId && visibleTravelers.length > 0 && (
            <div className="flex items-center" aria-hidden>
              {visibleTravelers.map((traveler, index) => (
                <span
                  key={traveler.id}
                  className={cn(
                    "-ml-2.5 flex size-[34px] items-center justify-center rounded-full border-[3px] border-white text-[13px] font-semibold first:ml-0",
                    ACCENT_FILL_CLASSES[accentAt(index)]
                  )}
                >
                  {traveler.name.charAt(0).toUpperCase()}
                </span>
              ))}
              {overflowCount > 0 && (
                <span
                  className={cn(
                    "-ml-2.5 flex size-[34px] items-center justify-center rounded-full border-[3px] border-white text-[13px] font-semibold",
                    ACCENT_FILL_CLASSES[accentAt(visibleTravelers.length)]
                  )}
                >
                  +{overflowCount}
                </span>
              )}
            </div>
          )}

          {tripId && isOrganizer && (
            <Dialog open={inviteOpen} onOpenChange={setInviteOpen}>
              <DialogTrigger
                render={
                  <Button
                    type="button"
                    className="h-auto rounded-pill bg-ink px-[22px] py-3 font-display text-[13px] font-bold text-white hover:bg-ink hover:brightness-110"
                  />
                }
              >
                Invite crew
              </DialogTrigger>
              <DialogContent>
                <DialogTitle className="mb-4 font-display text-lg font-bold text-ink">
                  Invite crew
                </DialogTitle>
                <form onSubmit={handleInvite} className="flex flex-col gap-3">
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="invite-email">Email</Label>
                    <Input
                      id="invite-email"
                      type="email"
                      required
                      autoComplete="email"
                      placeholder="friend@example.com"
                      value={inviteEmail}
                      onChange={(event) => setInviteEmail(event.target.value)}
                    />
                  </div>
                  <Button type="submit" disabled={inviteMember.isPending}>
                    {inviteMember.isPending ? "Inviting…" : "Invite"}
                  </Button>
                </form>
              </DialogContent>
            </Dialog>
          )}

          <Link
            href="/account"
            className={buttonVariants({ variant: "outline", size: "sm" })}
          >
            Account
          </Link>

          <Button variant="outline" size="sm" onClick={handleLogout}>
            Log out
          </Button>
        </div>
      </header>
      {/* min-h-0 overrides flexbox's default "never shrink below content height" for a
          flex-1 child in a column — without it this stays as tall as {children} needs and
          the fixed h-screen shell above does nothing. This is the shell's default scroll
          container; trip routes below stay exactly h-full within it (never taller), so
          this overflow-y-auto sits inert whenever one is mounted (app/(app)/trips/[tripId]/
          layout.tsx) and only actually scrolls for routes with no nested layout of their
          own (/trips, /trips/new). */}
      <main className="min-h-0 flex-1 overflow-y-auto">{children}</main>
    </div>
  );
}

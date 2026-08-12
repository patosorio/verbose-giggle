"use client";

import { useEffect, useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api-client";
import { useAuth, useUpdateDisplayName } from "@/lib/auth-context";

export default function AccountPage() {
  const { user } = useAuth();
  const updateDisplayName = useUpdateDisplayName();
  const [displayName, setDisplayName] = useState(user?.display_name ?? "");

  useEffect(() => {
    if (user?.display_name) {
      setDisplayName(user.display_name);
    }
  }, [user?.display_name]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = displayName.trim();
    if (!trimmed) {
      toast.error("Display name is required.");
      return;
    }
    try {
      await updateDisplayName.mutateAsync(trimmed);
      toast.success("Display name updated.");
    } catch (error) {
      toast.error(
        error instanceof ApiError
          ? error.message
          : "Could not update your display name."
      );
    }
  }

  if (!user) {
    return null;
  }

  return (
    <div className="mx-auto max-w-md px-6 py-10 md:px-14">
      <h1 className="font-display text-2xl font-bold text-ink">Account</h1>
      <form onSubmit={handleSubmit} className="mt-8 flex flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="account-email">Email</Label>
          <Input id="account-email" type="email" value={user.email} readOnly disabled />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="account-display-name">Display name</Label>
          <Input
            id="account-display-name"
            type="text"
            required
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
          />
        </div>
        <Button type="submit" disabled={updateDisplayName.isPending}>
          {updateDisplayName.isPending ? "Saving…" : "Save"}
        </Button>
      </form>
    </div>
  );
}

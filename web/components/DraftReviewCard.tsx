"use client";

import { FormEvent, useState } from "react";

import { isValidEmail } from "@/lib/email";
import type { DraftCard } from "@/lib/assistant";

type DraftReviewCardProps = {
  draft: DraftCard;
  backendUrl: string;
  onChange: (draft: DraftCard) => void;
  onResolved: (draft: DraftCard) => void;
};

export function DraftReviewCard({
  draft,
  backendUrl,
  onChange,
  onResolved,
}: DraftReviewCardProps) {
  const [error, setError] = useState<string | null>(null);
  const [isConfirming, setIsConfirming] = useState(false);
  const [isDiscarding, setIsDiscarding] = useState(false);
  const isOpen = draft.state === "open";
  const recipientInvalid =
    draft.recipient.trim().length > 0 && !isValidEmail(draft.recipient);
  const working = isConfirming || isDiscarding;
  const disabled = !isOpen || working;

  async function handleConfirm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (disabled) {
      return;
    }
    setError(null);
    setIsConfirming(true);
    try {
      const response = await fetch(`/api/drafts/${draft.id}/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          subject: draft.subject,
          body: draft.body,
          recipient: draft.recipient,
          ...(backendUrl.trim() ? { backendUrl: backendUrl.trim() } : {}),
        }),
      });
      const data = (await response.json()) as DraftCard & { error?: string };
      if (!response.ok) {
        setError(data.error ?? "Confirm failed.");
        return;
      }
      onResolved(data);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Confirm failed.");
    } finally {
      setIsConfirming(false);
    }
  }

  async function handleDiscard() {
    if (disabled) {
      return;
    }
    setError(null);
    setIsDiscarding(true);
    try {
      const response = await fetch(`/api/drafts/${draft.id}/discard`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          backendUrl.trim() ? { backendUrl: backendUrl.trim() } : {},
        ),
      });
      const data = (await response.json()) as DraftCard & { error?: string };
      if (!response.ok) {
        setError(data.error ?? "Discard failed.");
        return;
      }
      onResolved(data);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Discard failed.");
    } finally {
      setIsDiscarding(false);
    }
  }

  return (
    <form
      onSubmit={handleConfirm}
      className="mr-auto mt-3 w-full max-w-2xl rounded-xl border border-zinc-200 bg-zinc-50 p-4"
    >
      <div className="mb-3 flex items-center justify-between gap-2">
        <p className="text-xs font-semibold uppercase tracking-wider text-zinc-500">
          Draft
        </p>
        <span className="text-xs font-medium text-zinc-500">
          {draft.state === "sent"
            ? "Sent"
            : draft.state === "discarded"
              ? "Discarded"
              : "Open"}
        </span>
      </div>
      <label className="flex flex-col gap-1 text-sm">
        <span className="text-zinc-500">Subject</span>
        <input
          className="rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm outline-none ring-teal-500 focus:ring-2 disabled:bg-zinc-100"
          value={draft.subject}
          onChange={(event) =>
            onChange({ ...draft, subject: event.target.value })
          }
          disabled={disabled}
          aria-label="Draft subject"
        />
      </label>
      <label className="mt-3 flex flex-col gap-1 text-sm">
        <span className="text-zinc-500">Outbound email body</span>
        <textarea
          className="min-h-32 rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm outline-none ring-teal-500 focus:ring-2 disabled:bg-zinc-100"
          value={draft.body}
          onChange={(event) => onChange({ ...draft, body: event.target.value })}
          disabled={disabled}
          aria-label="Outbound email body"
        />
      </label>
      <label className="mt-3 flex flex-col gap-1 text-sm">
        <span className="text-zinc-500">Recipient</span>
        <input
          className="rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm outline-none ring-teal-500 focus:ring-2 disabled:bg-zinc-100"
          value={draft.recipient}
          onChange={(event) =>
            onChange({ ...draft, recipient: event.target.value })
          }
          disabled={disabled}
          aria-label="Draft recipient"
        />
        {recipientInvalid ? (
          <span className="text-xs text-rose-600">Enter a valid email address.</span>
        ) : null}
      </label>
      {error ? (
        <p className="mt-3 text-sm text-rose-600" role="alert">
          {error}
        </p>
      ) : null}
      {isOpen ? (
        <div className="mt-4 flex gap-2">
          <button
            type="submit"
            className="rounded-md bg-zinc-950 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-800 disabled:opacity-50"
            disabled={disabled}
          >
            {isConfirming ? "Confirming…" : "Confirm"}
          </button>
          <button
            type="button"
            className="rounded-md border border-zinc-300 px-4 py-2 text-sm font-medium text-zinc-700 hover:border-rose-400 hover:text-rose-700 disabled:opacity-50"
            onClick={() => void handleDiscard()}
            disabled={disabled}
          >
            {isDiscarding ? "Discarding…" : "Discard"}
          </button>
        </div>
      ) : null}
    </form>
  );
}

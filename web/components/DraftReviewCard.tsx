"use client";

import { isValidEmail } from "@/lib/email";
import type { DraftCard } from "@/lib/assistant";

type DraftReviewCardProps = {
  draft: DraftCard;
  locked: boolean;
  pending: "confirm" | "discard" | null;
  onChange: (draft: DraftCard) => void;
  onConfirm: (draft: DraftCard) => void;
  onDiscard: (draft: DraftCard) => void;
};

export function DraftReviewCard({
  draft,
  locked,
  pending,
  onChange,
  onConfirm,
  onDiscard,
}: DraftReviewCardProps) {
  const busy = pending !== null;
  const fieldsDisabled = locked || busy;
  const recipientValid = isValidEmail(draft.recipient);
  const label = draft.subject ? `Rascunho: ${draft.subject}` : "Rascunho";

  return (
    <article
      aria-label={label}
      className="rounded-xl border-2 bg-paper p-4"
      style={{ borderColor: "var(--act)" }}
    >
      <p className="text-xs font-semibold uppercase tracking-wider">Rascunho</p>
      <label className="mt-3 flex flex-col gap-1 text-sm">
        Assunto
        <input
          className="rounded-md border bg-paper px-3 py-2 text-sm outline-none"
          style={{ borderColor: "var(--line)" }}
          value={draft.subject}
          onChange={(event) =>
            onChange({ ...draft, subject: event.target.value })
          }
          disabled={fieldsDisabled}
        />
      </label>
      <label className="mt-3 flex flex-col gap-1 text-sm">
        Corpo do e-mail
        <textarea
          className="min-h-32 rounded-md border bg-paper px-3 py-2 text-sm outline-none"
          style={{ borderColor: "var(--line)" }}
          value={draft.body}
          onChange={(event) => onChange({ ...draft, body: event.target.value })}
          disabled={fieldsDisabled}
        />
      </label>
      <label className="mt-3 flex flex-col gap-1 text-sm">
        Destinatário
        <input
          className="rounded-md border bg-paper px-3 py-2 text-sm outline-none"
          style={{ borderColor: "var(--line)" }}
          value={draft.recipient}
          onChange={(event) =>
            onChange({ ...draft, recipient: event.target.value })
          }
          disabled={fieldsDisabled}
        />
      </label>
      <div className="mt-4 flex gap-2">
        <button
          type="button"
          className="rounded-md px-4 py-2 text-sm font-medium disabled:opacity-50"
          style={{ backgroundColor: "var(--act)", color: "var(--paper)" }}
          onClick={() => onConfirm(draft)}
          disabled={fieldsDisabled || !recipientValid}
        >
          {pending === "confirm" ? "Confirmando…" : "Confirmar envio"}
        </button>
        <button
          type="button"
          className="rounded-md border px-4 py-2 text-sm font-medium disabled:opacity-50"
          style={{ borderColor: "var(--line)" }}
          onClick={() => onDiscard(draft)}
          disabled={fieldsDisabled}
        >
          {pending === "discard" ? "Descartando…" : "Descartar"}
        </button>
      </div>
    </article>
  );
}

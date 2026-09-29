"use client";

import type { InboundEmail } from "@/lib/assistant";

type InboundEmailListProps = {
  emails: InboundEmail[];
  clip: boolean;
  onOpen: (email: InboundEmail) => void;
};

type OpenedInboundEmailProps = {
  email: InboundEmail;
  replyLocked: boolean;
  onBack: () => void;
  onReply: (email: InboundEmail) => void;
};

type ArrivalNoticesProps = {
  notices: InboundEmail[];
  onOpen: (email: InboundEmail) => void;
  onDismiss: (id: string) => void;
};

function clipClass(clip: boolean): string {
  return clip ? "inbound-clip" : "block whitespace-pre-wrap";
}

export function InboundEmailList({ emails, clip, onOpen }: InboundEmailListProps) {
  if (emails.length === 0) {
    return null;
  }
  return (
    <ul aria-label="E-mails recebidos" className="inbound-list flex flex-col gap-2">
      {emails.map((email) => (
        <li key={email.id} className="min-w-0">
          <a
            href={`#${email.id}`}
            className="block min-w-0 rounded-md px-2 py-2 text-sm"
            onClick={(event) => {
              event.preventDefault();
              onOpen(email);
            }}
          >
            <span className={clipClass(clip)}>{email.sender}</span>
            <span className={clipClass(clip)}>{email.subject}</span>
            <span className="block text-xs" style={{ color: "var(--muted)" }}>
              {email.date}
            </span>
            {email.unread ? (
              <span
                aria-label="Não lido"
                className="mt-1 inline-block h-2 w-2 rounded-full"
                style={{ backgroundColor: "var(--talk)" }}
              />
            ) : null}
          </a>
        </li>
      ))}
    </ul>
  );
}

export function OpenedInboundEmail({
  email,
  replyLocked,
  onBack,
  onReply,
}: OpenedInboundEmailProps) {
  const label = email.subject ? `E-mail: ${email.subject}` : "E-mail";
  return (
    <article aria-label={label} className="flex flex-col gap-3 text-sm">
      <p>
        <span className="font-medium">Remetente</span>
        <span className="mt-1 block whitespace-pre-wrap">{email.sender}</span>
      </p>
      <p>
        <span className="font-medium">Assunto</span>
        <span className="mt-1 block whitespace-pre-wrap">{email.subject}</span>
      </p>
      <p>
        <span className="font-medium">Data</span>
        <span className="mt-1 block">{email.date}</span>
      </p>
      <p className="whitespace-pre-wrap leading-6">{email.body}</p>
      <div className="flex gap-2">
        <button
          type="button"
          className="rounded-md border px-3 py-2 text-sm"
          style={{ borderColor: "var(--line)" }}
          onClick={onBack}
        >
          Voltar
        </button>
        <button
          type="button"
          className="rounded-md px-3 py-2 text-sm font-medium disabled:opacity-50"
          style={{ backgroundColor: "var(--talk)", color: "var(--paper)" }}
          onClick={() => onReply(email)}
          disabled={replyLocked}
        >
          Responder
        </button>
      </div>
    </article>
  );
}

export function ArrivalNotices({ notices, onOpen, onDismiss }: ArrivalNoticesProps) {
  if (notices.length === 0) {
    return null;
  }
  return (
    <section aria-label="Avisos de chegada" className="flex flex-col gap-2">
      {notices.map((notice) => (
        <article
          key={notice.id}
          aria-label={`Chegou: ${notice.subject || notice.sender}`}
          className="flex flex-wrap items-center gap-2 rounded-md border px-3 py-2 text-sm"
          style={{ borderColor: "var(--line)" }}
        >
          <button type="button" className="font-medium" onClick={() => onOpen(notice)}>
            {notice.sender}
          </button>
          <button type="button" onClick={() => onOpen(notice)}>
            {notice.subject}
          </button>
          <button type="button" className="ml-auto" onClick={() => onDismiss(notice.id)}>
            Dispensar
          </button>
        </article>
      ))}
    </section>
  );
}

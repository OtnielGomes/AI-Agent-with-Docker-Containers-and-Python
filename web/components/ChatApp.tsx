"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

import { DraftReviewCard } from "@/components/DraftReviewCard";
import type { DraftCard } from "@/lib/assistant";
import { isValidEmail } from "@/lib/email";

type TranscriptItem =
  | { kind: "user"; key: string; content: string }
  | { kind: "assistant"; key: string; content: string }
  | {
      kind: "sent" | "discarded";
      key: string;
      subject: string;
      body: string;
      recipient: string;
    };

type PendingAction = "confirm" | "discard";
type RecipientChoice = "inbox" | "other";
type MessageSource = "composer" | "example";

const EXAMPLE_PROMPTS = [
  "Resume meus últimos 3 e-mails.",
  "Escreva um e-mail sobre inteligência artificial aplicada a negócios.",
  "Ajude-me a escrever um e-mail para marcar uma reunião nesta semana.",
] as const;

const EMPTY_PIN_ALERT = "Informe o e-mail do destinatário.";
const INVALID_EMAIL_ALERT = "Informe um e-mail válido.";
const CONNECTION_ALERT = "Não foi possível falar com a API.";
const TIMEOUT_ALERT = "A resposta demorou demais.";
const CONFIRM_ALERT = "Não foi possível confirmar o envio.";
const DISCARD_ALERT = "Não foi possível descartar.";
const CLEAR_ALERT = "Não foi possível limpar a conversa.";
const WAIT_STATUS = "Preparando a resposta… Pode levar alguns minutos.";

function applyTurnDrafts(
  current: DraftCard[],
  incoming: DraftCard[],
  persistedRecipients: Map<string, string>,
): DraftCard[] {
  const next = [...current];
  for (const draft of incoming) {
    const index = next.findIndex((item) => item.id === draft.id);
    if (index === -1) {
      persistedRecipients.set(draft.id, draft.recipient);
      next.push(draft);
      continue;
    }
    const storedRecipient = persistedRecipients.get(draft.id);
    if (storedRecipient !== undefined && draft.recipient === storedRecipient) {
      next[index] = { ...draft, recipient: next[index].recipient };
      continue;
    }
    persistedRecipients.set(draft.id, draft.recipient);
    next[index] = draft;
  }
  return next;
}

function isDraftCard(value: unknown): value is DraftCard {
  if (!value || typeof value !== "object") {
    return false;
  }
  const item = value as Record<string, unknown>;
  return (
    typeof item.id === "string" &&
    typeof item.subject === "string" &&
    typeof item.body === "string" &&
    typeof item.recipient === "string" &&
    (item.state === "open" || item.state === "sent" || item.state === "discarded")
  );
}

function isTimeoutError(error: unknown): boolean {
  if (!error || typeof error !== "object" || !("name" in error)) {
    return false;
  }
  const name = String(error.name);
  return name === "TimeoutError" || name === "AbortError";
}

function alertForChatPayload(errorText: string): string {
  if (/timed out/i.test(errorText)) {
    return TIMEOUT_ALERT;
  }
  if (/could not connect/i.test(errorText)) {
    return CONNECTION_ALERT;
  }
  return errorText || CONNECTION_ALERT;
}

function clearQuestion(count: number): string {
  const noun = count === 1 ? "rascunho" : "rascunhos";
  return `Descartar ${count} ${noun} e limpar a conversa?`;
}

async function readJson(response: Response): Promise<Record<string, unknown>> {
  try {
    const data: unknown = await response.json();
    if (data && typeof data === "object") {
      return data as Record<string, unknown>;
    }
  } catch {
    // A non-JSON body still has an HTTP status the caller can use.
  }
  return {};
}

async function fetchHealth(): Promise<boolean> {
  try {
    const response = await fetch("/api/health", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
      signal: AbortSignal.timeout(8_000),
    });
    const data = await readJson(response);
    return response.ok && data.online === true;
  } catch {
    return false;
  }
}

async function fetchOpenDrafts(): Promise<DraftCard[]> {
  try {
    const response = await fetch("/api/drafts", {
      cache: "no-store",
      signal: AbortSignal.timeout(8_000),
    });
    const data = await readJson(response);
    if (!response.ok || !Array.isArray(data.drafts)) {
      return [];
    }
    return data.drafts.filter(isDraftCard);
  } catch {
    return [];
  }
}

async function fetchPriorRecipients(): Promise<string[]> {
  try {
    const response = await fetch("/api/drafts/prior-recipients", {
      cache: "no-store",
      signal: AbortSignal.timeout(8_000),
    });
    const data = await readJson(response);
    if (!response.ok || !Array.isArray(data.recipients)) {
      return [];
    }
    return data.recipients.filter((item): item is string => typeof item === "string");
  } catch {
    return [];
  }
}

function healthChip(online: boolean | null): { label: string; color: string } {
  if (online === null) {
    return { label: "Verificando…", color: "var(--ink)" };
  }
  if (online) {
    return { label: "API online", color: "var(--ink)" };
  }
  return { label: "API offline", color: "var(--danger)" };
}

export function ChatApp() {
  const [transcript, setTranscript] = useState<TranscriptItem[]>([]);
  const [reviewDrafts, setReviewDrafts] = useState<DraftCard[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);
  const [recipientChoice, setRecipientChoice] = useState<RecipientChoice>("inbox");
  const [otherRecipientEmail, setOtherRecipientEmail] = useState("");
  const [priorRecipients, setPriorRecipients] = useState<string[]>([]);
  const [alert, setAlert] = useState<string | null>(null);
  const [isSending, setIsSending] = useState(false);
  const [isClearing, setIsClearing] = useState(false);
  const [clearPrompt, setClearPrompt] = useState(false);
  const [pending, setPending] = useState<Record<string, PendingAction>>({});
  const persistedRecipients = useRef<Map<string, string>>(new Map());
  const keyRef = useRef(0);
  const transcriptRef = useRef<HTMLElement | null>(null);

  function nextKey(prefix: string): string {
    keyRef.current += 1;
    return `${prefix}-${keyRef.current}`;
  }

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const [online, drafts, recipients] = await Promise.all([
        fetchHealth(),
        fetchOpenDrafts(),
        fetchPriorRecipients(),
      ]);
      if (cancelled) {
        return;
      }
      setApiOnline(online);
      for (const draft of drafts) {
        persistedRecipients.current.set(draft.id, draft.recipient);
      }
      setReviewDrafts(drafts);
      setPriorRecipients(recipients);
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const node = transcriptRef.current;
    if (!node) {
      return;
    }
    node.scrollTop = node.scrollHeight;
  }, [transcript, isSending]);

  function updateDraft(next: DraftCard) {
    const updated = reviewDrafts.map((item) => (item.id === next.id ? next : item));
    setReviewDrafts(updated);
    if (updated.some((item) => !isValidEmail(item.recipient))) {
      setAlert(INVALID_EMAIL_ALERT);
      return;
    }
    setAlert((current) => (current === INVALID_EMAIL_ALERT ? null : current));
  }

  async function reloadPriorRecipients() {
    setPriorRecipients(await fetchPriorRecipients());
  }

  async function handleUserMessage(userText: string, source: MessageSource) {
    const text = userText.trim();
    if (!text || isSending || isClearing) {
      return;
    }

    let pinned: string | null = null;
    if (recipientChoice === "other") {
      pinned = otherRecipientEmail.trim();
      if (!pinned) {
        setAlert(EMPTY_PIN_ALERT);
        return;
      }
      if (!isValidEmail(pinned)) {
        setAlert(INVALID_EMAIL_ALERT);
        return;
      }
    }

    const snapshot = reviewDrafts.map((draft) => ({ ...draft }));
    const userKey = nextKey("user");
    setAlert(null);
    setTranscript((current) => [
      ...current,
      { kind: "user", key: userKey, content: text },
    ]);
    if (source === "composer") {
      setChatInput("");
    }
    setIsSending(true);

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          ...(pinned ? { to_email: pinned } : {}),
          open_drafts: snapshot.map((draft) => ({
            id: draft.id,
            subject: draft.subject,
            body: draft.body,
            recipient: draft.recipient,
          })),
        }),
      });
      const data = await readJson(response);
      const content = data.content;
      if (!response.ok || typeof content !== "string") {
        const errorText = typeof data.error === "string" ? data.error : "";
        setAlert(alertForChatPayload(errorText));
        setReviewDrafts(snapshot);
        if (source === "composer") {
          setChatInput(userText);
        }
        return;
      }

      const incoming = Array.isArray(data.drafts)
        ? data.drafts.filter(isDraftCard).filter((draft) => draft.state === "open")
        : [];
      const assistantKey = nextKey("assistant");
      setTranscript((current) => [
        ...current,
        { kind: "assistant", key: assistantKey, content },
      ]);
      setReviewDrafts(
        applyTurnDrafts(snapshot, incoming, persistedRecipients.current),
      );
    } catch (error) {
      setAlert(isTimeoutError(error) ? TIMEOUT_ALERT : CONNECTION_ALERT);
      setReviewDrafts(snapshot);
      if (source === "composer") {
        setChatInput(userText);
      }
    } finally {
      setIsSending(false);
    }
  }

  async function handleConfirm(draft: DraftCard) {
    if (isSending || pending[draft.id] || !isValidEmail(draft.recipient)) {
      if (!isValidEmail(draft.recipient)) {
        setAlert(INVALID_EMAIL_ALERT);
      }
      return;
    }
    setPending((current) => ({ ...current, [draft.id]: "confirm" }));
    try {
      const response = await fetch(`/api/drafts/${draft.id}/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          subject: draft.subject,
          body: draft.body,
          recipient: draft.recipient,
        }),
      });
      if (!response.ok) {
        setAlert(CONFIRM_ALERT);
        return;
      }
      const sentKey = nextKey("sent");
      setReviewDrafts((current) => current.filter((item) => item.id !== draft.id));
      setTranscript((current) => [
        ...current,
        {
          kind: "sent",
          key: sentKey,
          subject: draft.subject,
          body: draft.body,
          recipient: draft.recipient,
        },
      ]);
      setAlert(null);
      await reloadPriorRecipients();
    } catch {
      setAlert(CONFIRM_ALERT);
    } finally {
      setPending((current) => {
        const next = { ...current };
        delete next[draft.id];
        return next;
      });
    }
  }

  async function handleDiscard(draft: DraftCard) {
    if (isSending || pending[draft.id]) {
      return;
    }
    setPending((current) => ({ ...current, [draft.id]: "discard" }));
    try {
      const response = await fetch(`/api/drafts/${draft.id}/discard`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!response.ok) {
        setAlert(DISCARD_ALERT);
        return;
      }
      const discardedKey = nextKey("discarded");
      setReviewDrafts((current) => current.filter((item) => item.id !== draft.id));
      setTranscript((current) => [
        ...current,
        {
          kind: "discarded",
          key: discardedKey,
          subject: draft.subject,
          body: draft.body,
          recipient: draft.recipient,
        },
      ]);
      setAlert(null);
    } catch {
      setAlert(DISCARD_ALERT);
    } finally {
      setPending((current) => {
        const next = { ...current };
        delete next[draft.id];
        return next;
      });
    }
  }

  function requestClear() {
    if (isSending || isClearing) {
      return;
    }
    if (reviewDrafts.length === 0) {
      setTranscript([]);
      setAlert(null);
      setClearPrompt(false);
      return;
    }
    setClearPrompt(true);
  }

  async function confirmClear() {
    if (isSending || isClearing) {
      return;
    }
    setIsClearing(true);
    try {
      const response = await fetch("/api/drafts/discard-open", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!response.ok) {
        setAlert(CLEAR_ALERT);
        return;
      }
      setTranscript([]);
      setReviewDrafts([]);
      persistedRecipients.current.clear();
      setClearPrompt(false);
      setAlert(null);
    } catch {
      setAlert(CLEAR_ALERT);
    } finally {
      setIsClearing(false);
    }
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void handleUserMessage(chatInput, "composer");
  }

  const askingClear = clearPrompt && reviewDrafts.length > 0;
  const typedRecipient = otherRecipientEmail.trim();
  const recipientSuggestions =
    recipientChoice !== "other" || typedRecipient.length === 0
      ? []
      : priorRecipients.filter((address) =>
          address.toLowerCase().includes(typedRecipient.toLowerCase()),
        );
  const chip = healthChip(apiOnline);
  const composerLocked = isSending || isClearing;

  return (
    <div className="chat-shell">
      <aside className="chat-sidebar flex flex-col gap-6 px-5 py-6">
        <fieldset className="flex flex-col gap-3">
          <legend className="text-sm font-medium">Destinatário</legend>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="pinned-recipient"
              checked={recipientChoice === "inbox"}
              onChange={() => setRecipientChoice("inbox")}
            />
            Minha caixa de entrada
          </label>
          <p className="text-xs leading-5" style={{ color: "var(--muted)" }}>
            Os e-mails saem para o endereço configurado na aplicação.
          </p>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="pinned-recipient"
              checked={recipientChoice === "other"}
              onChange={() => setRecipientChoice("other")}
            />
            Outro destinatário
          </label>
          {recipientChoice === "other" ? (
            <label className="flex flex-col gap-2 text-sm">
              E-mail do destinatário
              <input
                className="rounded-md border bg-paper px-3 py-2 text-sm outline-none"
                style={{ borderColor: "var(--line)" }}
                value={otherRecipientEmail}
                onChange={(event) => setOtherRecipientEmail(event.target.value)}
              />
            </label>
          ) : null}
          {recipientSuggestions.length > 0 ? (
            <ul aria-label="Destinatários anteriores" className="flex flex-col">
              {recipientSuggestions.map((address) => (
                <li key={address}>
                  <button
                    type="button"
                    className="w-full rounded-md px-3 py-2 text-left text-sm hover:bg-quiet"
                    onClick={() => setOtherRecipientEmail(address)}
                  >
                    {address}
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </fieldset>

        <div className="flex flex-col gap-2">
          {EXAMPLE_PROMPTS.map((prompt) => (
            <button
              key={prompt}
              type="button"
              className="rounded-md border px-3 py-2 text-left text-sm disabled:opacity-50"
              style={{ borderColor: "var(--line)" }}
              onClick={() => void handleUserMessage(prompt, "example")}
              disabled={composerLocked}
            >
              {prompt}
            </button>
          ))}
        </div>

        {askingClear ? (
          <div className="mt-auto flex flex-col gap-2">
            <p className="text-sm">{clearQuestion(reviewDrafts.length)}</p>
            <button
              type="button"
              className="rounded-md border px-3 py-2 text-sm disabled:opacity-50"
              style={{ borderColor: "var(--line)" }}
              onClick={() => void confirmClear()}
              disabled={isClearing || isSending}
            >
              {isClearing ? "Limpando…" : "Limpar"}
            </button>
            <button
              type="button"
              className="rounded-md border px-3 py-2 text-sm disabled:opacity-50"
              style={{ borderColor: "var(--line)" }}
              onClick={() => setClearPrompt(false)}
              disabled={isClearing || isSending}
            >
              Voltar
            </button>
          </div>
        ) : (
          <button
            type="button"
            className="mt-auto rounded-md border px-3 py-2 text-sm disabled:opacity-50"
            style={{ borderColor: "var(--line)" }}
            onClick={requestClear}
            disabled={composerLocked}
          >
            Limpar conversa
          </button>
        )}
      </aside>

      <header className="chat-header flex items-start justify-between gap-4 border-b px-6 py-5" style={{ borderColor: "var(--line)" }}>
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Assistente de e-mail</h1>
          <p className="mt-1 text-sm" style={{ color: "var(--muted)" }}>
            Pesquisa, caixa de entrada e rascunhos.
          </p>
        </div>
        <span
          className="rounded-full px-3 py-1 text-sm font-medium"
          style={{ color: chip.color, backgroundColor: "var(--paper)" }}
        >
          {chip.label}
        </span>
      </header>

      <section
        ref={transcriptRef}
        aria-label="Conversa"
        className="chat-transcript flex flex-col gap-4 px-6 py-6"
      >
        {transcript.map((item) => {
          if (item.kind === "user") {
            return (
              <article
                key={item.key}
                aria-label="Você"
                className="ml-auto w-fit max-w-[80%] rounded-2xl px-4 py-3 text-sm"
                style={{ backgroundColor: "var(--talk)", color: "var(--paper)" }}
              >
                <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider">
                  Você
                </p>
                <p className="whitespace-pre-wrap leading-6">{item.content}</p>
              </article>
            );
          }
          if (item.kind === "assistant") {
            return (
              <article
                key={item.key}
                aria-label="Assistente"
                className="mr-auto w-fit max-w-[80%] rounded-2xl border px-4 py-3 text-sm"
                style={{ borderColor: "var(--line)", backgroundColor: "var(--paper)" }}
              >
                <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider">
                  Assistente
                </p>
                <p className="whitespace-pre-wrap leading-6">{item.content}</p>
              </article>
            );
          }
          const sent = item.kind === "sent";
          return (
            <article
              key={item.key}
              aria-label={`${sent ? "Enviado" : "Descartado"}: ${item.subject}`}
              className="mr-auto w-full max-w-2xl rounded-xl border p-4 text-sm"
              style={{
                borderColor: "var(--line)",
                opacity: sent ? 1 : 0.55,
              }}
            >
              <span
                className="inline-flex rounded-full px-2.5 py-1 text-xs font-medium"
                style={
                  sent
                    ? { backgroundColor: "var(--quiet)", color: "var(--ink)" }
                    : { color: "var(--ink)" }
                }
              >
                {sent ? "Enviado" : "Descartado"}
              </span>
              <p className="mt-3">
                <span className="font-medium">Assunto</span>
                <span className="mt-1 block whitespace-pre-wrap">{item.subject}</span>
              </p>
              <p className="mt-3">
                <span className="font-medium">Corpo do e-mail</span>
                <span
                  className="mt-1 block whitespace-pre-wrap"
                  style={{ textDecorationLine: "none" }}
                >
                  {item.body}
                </span>
              </p>
              <p className="mt-3">
                <span className="font-medium">Destinatário</span>
                <span className="mt-1 block">{item.recipient}</span>
              </p>
            </article>
          );
        })}
        {isSending ? <p className="text-sm">{WAIT_STATUS}</p> : null}
      </section>

      {reviewDrafts.length > 0 ? (
        <section aria-label="Rascunhos" className="chat-review flex flex-col gap-3 px-4 py-4">
          {reviewDrafts.map((draft) => (
            <DraftReviewCard
              key={draft.id}
              draft={draft}
              locked={isSending}
              pending={pending[draft.id] ?? null}
              onChange={updateDraft}
              onConfirm={(next) => void handleConfirm(next)}
              onDiscard={(next) => void handleDiscard(next)}
            />
          ))}
        </section>
      ) : null}

      <form onSubmit={onSubmit} className="chat-composer px-6 py-4">
        {alert ? (
          <p className="mb-3 text-sm" role="alert" style={{ color: "var(--danger)" }}>
            {alert}
          </p>
        ) : null}
        <div className="flex items-end gap-3">
          <textarea
            aria-label="Mensagem"
            className="min-h-12 flex-1 resize-y rounded-xl border bg-paper px-4 py-3 text-sm outline-none disabled:opacity-50"
            style={{ borderColor: "var(--line)" }}
            value={chatInput}
            rows={2}
            onChange={(event) => setChatInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void handleUserMessage(chatInput, "composer");
              }
            }}
            disabled={composerLocked}
          />
          <button
            type="submit"
            className="rounded-xl px-5 py-3 text-sm font-medium disabled:opacity-50"
            style={{ backgroundColor: "var(--talk)", color: "var(--paper)" }}
            disabled={composerLocked || !chatInput.trim()}
          >
            Enviar mensagem
          </button>
        </div>
      </form>
    </div>
  );
}

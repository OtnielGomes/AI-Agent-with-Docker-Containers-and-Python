"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

import { isValidEmail } from "@/lib/email";

type ChatRole = "user" | "assistant";
type ChatTurn = { role: ChatRole; content: string };

const EXAMPLE_PROMPTS = [
  "Summarize my last 3 emails.",
  "Write me an email about artificial intelligence applied to business.",
  "Help me write an email to schedule a meeting for this week.",
];

export function ChatApp() {
  const [messages, setMessages] = useState<ChatTurn[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [backendUrl, setBackendUrl] = useState("");
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);
  const [sendToSelf, setSendToSelf] = useState(true);
  const [otherRecipientEmail, setOtherRecipientEmail] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [isSending, setIsSending] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function loadConfig() {
      try {
        const response = await fetch("/api/config");
        const data = (await response.json()) as { backendUrl?: string };
        const url =
          typeof data.backendUrl === "string" ? data.backendUrl.trim() : "";
        if (!cancelled && url) {
          setBackendUrl(url);
        }
        if (!cancelled) {
          await refreshHealth(url || undefined);
        }
      } catch {
        if (!cancelled) {
          await refreshHealth();
        }
      }
    }
    void loadConfig();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isSending]);

  async function refreshHealth(url?: string) {
    const override = (url ?? backendUrl).trim();
    setIsTesting(true);
    try {
      const response = await fetch("/api/health", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(override ? { backendUrl: override } : {}),
        signal: AbortSignal.timeout(8_000),
      });
      const data = (await response.json()) as { online?: boolean };
      setApiOnline(Boolean(data.online));
    } catch {
      setApiOnline(false);
    } finally {
      setIsTesting(false);
    }
  }

  function selectedRecipient(): string | null {
    if (sendToSelf) {
      return null;
    }
    const email = otherRecipientEmail.trim();
    return email || null;
  }

  async function handleUserMessage(userText: string) {
    const text = userText.trim();
    if (!text || isSending) {
      return;
    }

    const pinned = selectedRecipient();
    if (!sendToSelf) {
      if (!pinned) {
        setFormError("Enter the recipient's email in the sidebar..");
        return;
      }
      if (!isValidEmail(pinned)) {
        setFormError("Invalid recipient email.");
        return;
      }
    }

    setFormError(null);
    setChatInput("");
    setMessages((current) => [...current, { role: "user", content: text }]);
    setIsSending(true);

    let reply: string;
    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          ...(backendUrl.trim() ? { backendUrl: backendUrl.trim() } : {}),
          ...(pinned ? { to_email: pinned } : {}),
        }),
      });
      const data = (await response.json()) as {
        content?: string;
        error?: string;
      };
      if (!response.ok || data.content == null) {
        reply = `**Error:** ${data.error ?? "Request failed."}`;
      } else {
        reply = data.content;
      }
    } catch (error) {
      reply = `**Error:** ${error instanceof Error ? error.message : "Request failed."}`;
    }

    setMessages((current) => [...current, { role: "assistant", content: reply }]);
    setIsSending(false);
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void handleUserMessage(chatInput);
  }

  const recipientHintInvalid =
    !sendToSelf &&
    otherRecipientEmail.trim().length > 0 &&
    !isValidEmail(otherRecipientEmail);

  return (
    <div className="flex min-h-full bg-zinc-50 text-zinc-900">
      <aside className="flex w-80 shrink-0 flex-col gap-6 overflow-y-auto border-r border-zinc-800 bg-zinc-950 px-5 py-6 text-zinc-100">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-teal-400">
            Settings
          </p>
          <h1 className="mt-2 text-lg font-semibold">Chat assistant</h1>
        </div>

        <label className="flex flex-col gap-2 text-sm">
          <span className="text-zinc-400">Backend URL</span>
          <input
            className="rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none ring-teal-400 focus:ring-2"
            value={backendUrl}
            onChange={(event) => setBackendUrl(event.target.value)}
            aria-label="Backend URL"
          />
        </label>

        <button
          type="button"
          className="w-full rounded-md bg-teal-500 px-3 py-2 text-sm font-medium text-zinc-950 hover:bg-teal-400 disabled:opacity-60"
          onClick={() => void refreshHealth(backendUrl)}
          disabled={isTesting}
        >
          {isTesting ? "Testing…" : "Test connection"}
        </button>

        <div>
          <p className="text-sm font-medium text-zinc-300">Email recipient</p>
          <label className="mt-3 flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              name="send-to-self"
              checked={sendToSelf}
              onChange={(event) => {
                setSendToSelf(event.target.checked);
                if (event.target.checked) {
                  setFormError(null);
                }
              }}
            />
            Send an email to myself
          </label>
          <label className="mt-2 flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              name="other-email"
              checked={!sendToSelf}
              onChange={(event) => {
                setSendToSelf(!event.target.checked);
                if (event.target.checked) {
                  setFormError(null);
                }
              }}
            />
            Other email
          </label>
          {sendToSelf ? (
            <p className="mt-3 text-xs leading-5 text-zinc-400">
              The emails will be sent to the primary email address configured in
              the app.
            </p>
          ) : (
            <label className="mt-3 flex flex-col gap-2 text-sm">
              <span className="text-zinc-400">Recipient&apos;s email</span>
              <input
                className="rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none ring-teal-400 focus:ring-2"
                value={otherRecipientEmail}
                placeholder="name@exemple.com"
                onChange={(event) => setOtherRecipientEmail(event.target.value)}
                aria-label="Recipient's email"
              />
              {recipientHintInvalid ? (
                <span className="text-xs text-rose-400">
                  Enter a valid email address..
                </span>
              ) : null}
            </label>
          )}
        </div>

        <div>
          <p className="text-sm font-medium text-zinc-300">Example prompts</p>
          <div className="mt-3 flex flex-col gap-2">
            {EXAMPLE_PROMPTS.map((prompt) => (
              <button
                key={prompt}
                type="button"
                className="rounded-md border border-zinc-700 px-3 py-2 text-left text-sm text-zinc-200 hover:border-teal-400 hover:text-white"
                onClick={() => void handleUserMessage(prompt)}
                disabled={isSending}
              >
                {prompt}
              </button>
            ))}
          </div>
        </div>

        <button
          type="button"
          className="mt-auto rounded-md border border-zinc-700 px-3 py-2 text-sm text-zinc-300 hover:border-rose-400 hover:text-rose-300"
          onClick={() => {
            setMessages([]);
            setFormError(null);
          }}
        >
          Clear chat
        </button>
      </aside>

      <main className="flex min-h-full flex-1 flex-col">
        <header className="flex items-start justify-between gap-4 border-b border-zinc-200 bg-white px-8 py-5">
          <div>
            <h2 className="text-2xl font-semibold tracking-tight">
              AI Agent Chat
            </h2>
            <p className="mt-1 text-sm text-zinc-500">
              Research and email assistant powered by LangGraph. History is kept
              for this session only.
            </p>
          </div>
          <span
            className={
              apiOnline == null
                ? "rounded-full bg-zinc-100 px-3 py-1 text-sm font-medium text-zinc-600"
                : apiOnline
                  ? "rounded-full bg-emerald-100 px-3 py-1 text-sm font-medium text-emerald-800"
                  : "rounded-full bg-rose-100 px-3 py-1 text-sm font-medium text-rose-800"
            }
          >
            {apiOnline == null
              ? "Checking…"
              : apiOnline
                ? "API online"
                : "API offline"}
          </span>
        </header>

        <section className="flex flex-1 flex-col gap-4 overflow-y-auto px-8 py-6">
          {messages.length === 0 ? (
            <p className="text-sm text-zinc-500">
              Ask the agent to research a topic, read the inbox, or send an
              email.
            </p>
          ) : null}
          {messages.map((turn, index) => (
            <article
              key={`${turn.role}-${index}`}
              className={
                turn.role === "user"
                  ? "ml-auto max-w-2xl rounded-2xl bg-teal-600 px-4 py-3 text-sm text-white"
                  : "mr-auto max-w-2xl rounded-2xl border border-zinc-200 bg-white px-4 py-3 text-sm text-zinc-800"
              }
            >
              <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider opacity-70">
                {turn.role === "user" ? "You" : "Assistant"}
              </p>
              <pre className="whitespace-pre-wrap font-sans leading-6">
                {turn.content.replace(/\*\*(.*?)\*\*/g, "$1")}
              </pre>
            </article>
          ))}
          {isSending ? (
            <p className="text-sm text-zinc-500">
              Agent is working... This may take up to a few minutes.
            </p>
          ) : null}
          {formError ? (
            <p className="text-sm text-rose-600" role="alert">
              {formError}
            </p>
          ) : null}
          <div ref={bottomRef} />
        </section>

        <form
          onSubmit={onSubmit}
          className="border-t border-zinc-200 bg-white px-8 py-4"
        >
          <div className="flex gap-3">
            <input
              className="flex-1 rounded-xl border border-zinc-300 px-4 py-3 text-sm outline-none ring-teal-500 focus:ring-2"
              value={chatInput}
              onChange={(event) => setChatInput(event.target.value)}
              placeholder="Ask the agent..."
              disabled={isSending}
              aria-label="Chat message"
            />
            <button
              type="submit"
              className="rounded-xl bg-zinc-950 px-5 py-3 text-sm font-medium text-white hover:bg-zinc-800 disabled:opacity-50"
              disabled={isSending || !chatInput.trim()}
            >
              Send
            </button>
          </div>
        </form>
      </main>
    </div>
  );
}

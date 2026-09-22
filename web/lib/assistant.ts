const DEFAULT_BACKEND_URL = "http://localhost:8080";
const HEALTH_TIMEOUT_MS = 5_000;
const CHAT_TIMEOUT_MS = 300_000;
const DRAFT_TIMEOUT_MS = 30_000;

export class AssistantError extends Error {}

export type DraftState = "open" | "sent" | "discarded";

export type DraftCard = {
  id: string;
  subject: string;
  body: string;
  recipient: string;
  state: DraftState;
};

export type ChatTurnResponse = {
  content: string;
  drafts: DraftCard[];
};

export function resolveBackendUrl(override?: string | null): string {
  const raw = (override ?? process.env.BACKEND_URL ?? DEFAULT_BACKEND_URL).trim();
  return raw.replace(/\/$/, "") || DEFAULT_BACKEND_URL;
}

async function fetchWithTimeout(
  url: string,
  init: RequestInit,
  timeoutMs: number,
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, {
      ...init,
      cache: "no-store",
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timer);
  }
}

function connectionError(error: unknown, timeoutMessage: string): AssistantError {
  if (
    error instanceof Error &&
    (error.name === "TimeoutError" || error.name === "AbortError")
  ) {
    return new AssistantError(timeoutMessage);
  }
  return new AssistantError(
    "Could not connect to the backend. Check that the API is running.",
  );
}

async function readAssistantError(response: Response): Promise<AssistantError> {
  let detail = await response.text();
  try {
    const body = JSON.parse(detail) as { detail?: string; error?: string };
    detail = body.detail ?? body.error ?? detail;
  } catch {
    // Keep the raw response text.
  }
  return new AssistantError(`API error (${response.status}): ${detail}`);
}

function parseDraft(raw: unknown): DraftCard | null {
  if (!raw || typeof raw !== "object") {
    return null;
  }
  const item = raw as Record<string, unknown>;
  if (
    typeof item.id !== "string" ||
    typeof item.subject !== "string" ||
    typeof item.body !== "string" ||
    typeof item.recipient !== "string" ||
    (item.state !== "open" &&
      item.state !== "sent" &&
      item.state !== "discarded")
  ) {
    return null;
  }
  return {
    id: item.id,
    subject: item.subject,
    body: item.body,
    recipient: item.recipient,
    state: item.state,
  };
}

function parseDrafts(raw: unknown): DraftCard[] {
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw.flatMap((item) => {
    const draft = parseDraft(item);
    return draft ? [draft] : [];
  });
}

export async function checkAssistantHealth(baseUrl: string): Promise<boolean> {
  try {
    const response = await fetchWithTimeout(
      `${baseUrl}/api/chats/`,
      {},
      HEALTH_TIMEOUT_MS,
    );
    if (!response.ok) {
      return false;
    }
    const data = (await response.json()) as { status?: string };
    return data.status === "ok";
  } catch {
    return false;
  }
}

export type OpenDraftSnapshot = {
  id: string;
  subject: string;
  body: string;
  recipient: string;
};

export async function sendChatMessage(
  baseUrl: string,
  message: string,
  pinnedRecipient?: string | null,
  openDrafts: OpenDraftSnapshot[] = [],
): Promise<ChatTurnResponse> {
  const payload: {
    message: string;
    to_email?: string;
    open_drafts: OpenDraftSnapshot[];
  } = { message, open_drafts: openDrafts };
  if (pinnedRecipient) {
    payload.to_email = pinnedRecipient;
  }

  let response: Response;
  try {
    response = await fetchWithTimeout(
      `${baseUrl}/api/chats/`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
      CHAT_TIMEOUT_MS,
    );
  } catch (error) {
    throw connectionError(
      error,
      "Request timed out. Research and email flows can take several minutes.",
    );
  }

  if (!response.ok) {
    throw await readAssistantError(response);
  }

  let data: { content?: unknown; drafts?: unknown };
  try {
    data = (await response.json()) as { content?: unknown; drafts?: unknown };
  } catch {
    throw new AssistantError("Invalid JSON response from backend.");
  }

  if (data.content == null) {
    throw new AssistantError("Backend response missing 'content' field.");
  }
  return {
    content: String(data.content),
    drafts: parseDrafts(data.drafts),
  };
}

export async function confirmDraft(
  baseUrl: string,
  draft: {
    id: string;
    subject: string;
    body: string;
    recipient: string;
  },
): Promise<DraftCard> {
  let response: Response;
  try {
    response = await fetchWithTimeout(
      `${baseUrl}/api/drafts/${draft.id}/confirm`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          subject: draft.subject,
          body: draft.body,
          recipient: draft.recipient,
        }),
      },
      DRAFT_TIMEOUT_MS,
    );
  } catch (error) {
    throw connectionError(error, "Confirm timed out.");
  }

  if (!response.ok) {
    throw await readAssistantError(response);
  }

  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new AssistantError("Invalid JSON response from backend.");
  }

  const parsed = parseDraft(data);
  if (!parsed) {
    throw new AssistantError("Backend response missing a Draft.");
  }
  return parsed;
}

export async function discardDraft(
  baseUrl: string,
  draftId: string,
): Promise<DraftCard> {
  let response: Response;
  try {
    response = await fetchWithTimeout(
      `${baseUrl}/api/drafts/${draftId}/discard`,
      { method: "POST" },
      DRAFT_TIMEOUT_MS,
    );
  } catch (error) {
    throw connectionError(error, "Discard timed out.");
  }

  if (!response.ok) {
    throw await readAssistantError(response);
  }

  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new AssistantError("Invalid JSON response from backend.");
  }

  const parsed = parseDraft(data);
  if (!parsed) {
    throw new AssistantError("Backend response missing a Draft.");
  }
  return parsed;
}

export async function discardOpenDrafts(baseUrl: string): Promise<DraftCard[]> {
  let response: Response;
  try {
    response = await fetchWithTimeout(
      `${baseUrl}/api/drafts/discard-open`,
      { method: "POST" },
      DRAFT_TIMEOUT_MS,
    );
  } catch (error) {
    throw connectionError(error, "Discard timed out.");
  }

  if (!response.ok) {
    throw await readAssistantError(response);
  }

  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new AssistantError("Invalid JSON response from backend.");
  }

  return parseDrafts(data);
}

export async function listPriorRecipients(baseUrl: string): Promise<string[]> {
  let response: Response;
  try {
    response = await fetchWithTimeout(
      `${baseUrl}/api/drafts/prior-recipients`,
      {},
      DRAFT_TIMEOUT_MS,
    );
  } catch (error) {
    throw connectionError(error, "Could not load prior recipients.");
  }

  if (!response.ok) {
    throw await readAssistantError(response);
  }

  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new AssistantError("Invalid JSON response from backend.");
  }

  if (!Array.isArray(data)) {
    return [];
  }
  return data.filter((item): item is string => typeof item === "string");
}

export async function listOpenDrafts(baseUrl: string): Promise<DraftCard[]> {
  let response: Response;
  try {
    response = await fetchWithTimeout(
      `${baseUrl}/api/drafts/`,
      {},
      DRAFT_TIMEOUT_MS,
    );
  } catch (error) {
    throw connectionError(error, "Could not load open Drafts.");
  }

  if (!response.ok) {
    throw await readAssistantError(response);
  }

  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new AssistantError("Invalid JSON response from backend.");
  }

  return parseDrafts(data);
}

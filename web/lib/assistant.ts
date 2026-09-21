const DEFAULT_BACKEND_URL = "http://localhost:8080";
const HEALTH_TIMEOUT_MS = 5_000;
const CHAT_TIMEOUT_MS = 300_000;

export class AssistantError extends Error {}

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

export async function sendChatMessage(
  baseUrl: string,
  message: string,
  pinnedRecipient?: string | null,
): Promise<string> {
  const payload: { message: string; to_email?: string } = { message };
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
    if (
      error instanceof Error &&
      (error.name === "TimeoutError" || error.name === "AbortError")
    ) {
      throw new AssistantError(
        "Request timed out. Research and email flows can take several minutes.",
      );
    }
    throw new AssistantError(
      "Could not connect to the backend. Check that the API is running.",
    );
  }

  if (!response.ok) {
    let detail = await response.text();
    try {
      const body = JSON.parse(detail) as { detail?: string };
      detail = body.detail ?? detail;
    } catch {
      // Keep the raw response text.
    }
    throw new AssistantError(`API error (${response.status}): ${detail}`);
  }

  let data: { content?: unknown };
  try {
    data = (await response.json()) as { content?: unknown };
  } catch {
    throw new AssistantError("Invalid JSON response from backend.");
  }

  if (data.content == null) {
    throw new AssistantError("Backend response missing 'content' field.");
  }
  return String(data.content);
}

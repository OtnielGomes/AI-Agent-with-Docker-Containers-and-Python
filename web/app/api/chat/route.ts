import {
  AssistantError,
  resolveBackendUrl,
  sendChatMessage,
  type InboundEmailSnapshot,
  type OpenDraftSnapshot,
} from "@/lib/assistant";

function openDraftSnapshots(raw: unknown): OpenDraftSnapshot[] {
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw.flatMap((item) => {
    if (!item || typeof item !== "object") {
      return [];
    }
    const draft = item as Record<string, unknown>;
    if (
      typeof draft.id !== "string" ||
      typeof draft.subject !== "string" ||
      typeof draft.body !== "string" ||
      typeof draft.recipient !== "string"
    ) {
      return [];
    }
    return [
      {
        id: draft.id,
        subject: draft.subject,
        body: draft.body,
        recipient: draft.recipient,
      },
    ];
  });
}

function inboundSnapshots(raw: unknown): InboundEmailSnapshot[] {
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw.flatMap((item) => {
    if (!item || typeof item !== "object") {
      return [];
    }
    const email = item as Record<string, unknown>;
    if (typeof email.id !== "string") {
      return [];
    }
    return [
      {
        id: email.id,
        sender: typeof email.sender === "string" ? email.sender : "",
        address: typeof email.address === "string" ? email.address : "",
        subject: typeof email.subject === "string" ? email.subject : "",
        date: typeof email.date === "string" ? email.date : "",
        body: typeof email.body === "string" ? email.body : "",
      },
    ];
  });
}

export const dynamic = "force-dynamic";
export const maxDuration = 300;

export async function POST(request: Request) {
  const body = (await request.json().catch(() => ({}))) as {
    message?: unknown;
    to_email?: unknown;
    backendUrl?: unknown;
    open_drafts?: unknown;
    inbound_emails?: unknown;
  };
  const message = typeof body.message === "string" ? body.message.trim() : "";
  if (!message) {
    return Response.json({ error: "Message is required." }, { status: 400 });
  }

  const override =
    typeof body.backendUrl === "string" ? body.backendUrl : undefined;
  const pinnedRecipient =
    typeof body.to_email === "string" && body.to_email.trim()
      ? body.to_email.trim()
      : null;

  try {
    const result = await sendChatMessage(
      resolveBackendUrl(override),
      message,
      pinnedRecipient,
      openDraftSnapshots(body.open_drafts),
      inboundSnapshots(body.inbound_emails),
    );
    return Response.json(result);
  } catch (error) {
    const text =
      error instanceof AssistantError
        ? error.message
        : "Could not connect to the backend. Check that the API is running.";
    return Response.json({ error: text }, { status: 502 });
  }
}

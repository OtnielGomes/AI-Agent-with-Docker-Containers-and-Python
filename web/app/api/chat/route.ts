import {
  AssistantError,
  resolveBackendUrl,
  sendChatMessage,
} from "@/lib/assistant";

export const dynamic = "force-dynamic";
export const maxDuration = 300;

export async function POST(request: Request) {
  const body = (await request.json().catch(() => ({}))) as {
    message?: unknown;
    to_email?: unknown;
    backendUrl?: unknown;
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
    const content = await sendChatMessage(
      resolveBackendUrl(override),
      message,
      pinnedRecipient,
    );
    return Response.json({ content });
  } catch (error) {
    const text =
      error instanceof AssistantError
        ? error.message
        : "Could not connect to the backend. Check that the API is running.";
    return Response.json({ error: text }, { status: 502 });
  }
}

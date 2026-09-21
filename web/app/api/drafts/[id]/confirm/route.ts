import {
  AssistantError,
  confirmDraft,
  resolveBackendUrl,
} from "@/lib/assistant";

export const dynamic = "force-dynamic";

export async function POST(
  request: Request,
  context: { params: Promise<{ id: string }> },
) {
  const { id } = await context.params;
  const body = (await request.json().catch(() => ({}))) as {
    subject?: unknown;
    body?: unknown;
    recipient?: unknown;
    backendUrl?: unknown;
  };

  const subject = typeof body.subject === "string" ? body.subject : "";
  const outboundBody = typeof body.body === "string" ? body.body : "";
  const recipient = typeof body.recipient === "string" ? body.recipient : "";
  if (!id) {
    return Response.json({ error: "Draft id is required." }, { status: 400 });
  }

  const override =
    typeof body.backendUrl === "string" ? body.backendUrl : undefined;

  try {
    const draft = await confirmDraft(resolveBackendUrl(override), {
      id,
      subject,
      body: outboundBody,
      recipient,
    });
    return Response.json(draft);
  } catch (error) {
    const text =
      error instanceof AssistantError
        ? error.message
        : "Could not connect to the backend. Check that the API is running.";
    return Response.json({ error: text }, { status: 502 });
  }
}

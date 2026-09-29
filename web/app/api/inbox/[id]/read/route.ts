import { AssistantError, markInboundRead, resolveBackendUrl } from "@/lib/assistant";

export const dynamic = "force-dynamic";

export async function POST(
  request: Request,
  context: { params: Promise<{ id: string }> },
) {
  const { id } = await context.params;
  const body = (await request.json().catch(() => ({}))) as { backendUrl?: unknown };
  const override = typeof body.backendUrl === "string" ? body.backendUrl : undefined;
  if (!id) {
    return Response.json({ error: "Inbound email id is required." }, { status: 400 });
  }

  try {
    await markInboundRead(resolveBackendUrl(override), id);
    return Response.json({ id, unread: false });
  } catch (error) {
    const text =
      error instanceof AssistantError
        ? error.message
        : "Could not connect to the backend. Check that the API is running.";
    return Response.json({ error: text }, { status: 502 });
  }
}

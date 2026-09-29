import {
  AssistantError,
  discardDraft,
  resolveBackendUrl,
} from "@/lib/assistant";

export const dynamic = "force-dynamic";

export async function POST(
  request: Request,
  context: { params: Promise<{ id: string }> },
) {
  const { id } = await context.params;
  const body = (await request.json().catch(() => ({}))) as {
    backendUrl?: unknown;
  };
  if (!id) {
    return Response.json({ error: "Draft id is required." }, { status: 400 });
  }

  const override =
    typeof body.backendUrl === "string" ? body.backendUrl : undefined;

  try {
    const draft = await discardDraft(resolveBackendUrl(override), id);
    return Response.json(draft);
  } catch (error) {
    const text =
      error instanceof AssistantError
        ? error.message
        : "Could not connect to the backend. Check that the API is running.";
    return Response.json({ error: text }, { status: 502 });
  }
}

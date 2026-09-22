import {
  AssistantError,
  discardOpenDrafts,
  resolveBackendUrl,
} from "@/lib/assistant";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const body = (await request.json().catch(() => ({}))) as {
    backendUrl?: unknown;
  };
  const override =
    typeof body.backendUrl === "string" ? body.backendUrl : undefined;

  try {
    const drafts = await discardOpenDrafts(resolveBackendUrl(override));
    return Response.json({ drafts });
  } catch (error) {
    const text =
      error instanceof AssistantError
        ? error.message
        : "Could not connect to the backend. Check that the API is running.";
    return Response.json({ error: text }, { status: 502 });
  }
}

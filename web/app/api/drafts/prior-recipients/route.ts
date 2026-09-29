import {
  AssistantError,
  listPriorRecipients,
  resolveBackendUrl,
} from "@/lib/assistant";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const requested = new URL(request.url).searchParams.get("backendUrl");
  const override = requested && requested.trim() ? requested : undefined;

  try {
    const recipients = await listPriorRecipients(resolveBackendUrl(override));
    return Response.json({ recipients });
  } catch (error) {
    const text =
      error instanceof AssistantError
        ? error.message
        : "Could not connect to the backend. Check that the API is running.";
    return Response.json({ error: text }, { status: 502 });
  }
}

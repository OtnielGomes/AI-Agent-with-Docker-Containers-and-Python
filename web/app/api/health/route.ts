import { checkAssistantHealth, resolveBackendUrl } from "@/lib/assistant";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const body = (await request.json().catch(() => ({}))) as {
    backendUrl?: unknown;
  };
  const override =
    typeof body.backendUrl === "string" ? body.backendUrl : undefined;
  const online = await checkAssistantHealth(resolveBackendUrl(override));
  return Response.json({ online });
}

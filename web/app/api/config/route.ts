import { resolveBackendUrl } from "@/lib/assistant";

export const dynamic = "force-dynamic";

export async function GET() {
  return Response.json({ backendUrl: resolveBackendUrl() });
}

import type {
  CarePlanDetail,
  CarePlanSummary,
  RunCreated,
  RunDetail,
  RunStatus,
  RunSummary,
  ReviewAction,
  SystemHealth,
} from "@app/api/models";

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new ApiError(res.status, text);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

const B = "/api/v1";

// --- Runs ---
export async function createRun(
  ipsBundle: Record<string, unknown>,
): Promise<RunCreated> {
  return request(`${B}/runs`, {
    method: "POST",
    body: JSON.stringify({ ipsBundle }),
  });
}

export async function listRuns(filters?: {
  status?: RunStatus;
  limit?: number;
}): Promise<RunSummary[]> {
  const params = new URLSearchParams();
  if (filters?.status) params.set("status", filters.status);
  if (filters?.limit != null) params.set("limit", String(filters.limit));
  const qs = params.toString();
  return request(`${B}/runs${qs ? `?${qs}` : ""}`);
}

export async function getRunDetail(runId: string): Promise<RunDetail> {
  return request(`${B}/runs/${runId}`);
}

export async function cancelRun(runId: string): Promise<void> {
  return request(`${B}/runs/${runId}`, { method: "DELETE" });
}

export async function submitReview(
  runId: string,
  action: ReviewAction,
): Promise<RunDetail> {
  return request(`${B}/runs/${runId}/review/careplan`, {
    method: "POST",
    body: JSON.stringify(action),
  });
}

// --- Care plans (persisted, read-only) ---
export async function listCarePlans(): Promise<CarePlanSummary[]> {
  return request(`${B}/careplans`);
}

export async function getCarePlan(id: string): Promise<CarePlanDetail> {
  return request(`${B}/careplans/${id}`);
}

// --- Status ---
export async function getSystemStatus(): Promise<SystemHealth> {
  return request(`${B}/status`);
}

export async function healthCheck(): Promise<{ status: string }> {
  return request("/health");
}

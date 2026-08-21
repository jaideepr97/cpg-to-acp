import { http, HttpResponse } from "msw";
import type { ReviewAction } from "@app/api/models";
import {
  carePlanDetail,
  carePlanSummaries,
  runAwaitingReview,
  runCompleted,
  runRunning,
  runSummaries,
  systemHealth,
} from "./fixtures";

const B = "/api/v1";

export const handlers = [
  http.get(`${B}/runs`, () => HttpResponse.json(runSummaries)),

  http.post(`${B}/runs`, async () =>
    HttpResponse.json({ runId: "run-123", status: "running" }, { status: 202 }),
  ),

  http.get(`${B}/runs/:runId`, ({ params }) => {
    if (params.runId === "run-review") return HttpResponse.json(runAwaitingReview);
    if (params.runId === "run-done") return HttpResponse.json(runCompleted);
    return HttpResponse.json(runRunning);
  }),

  http.delete(`${B}/runs/:runId`, () => new HttpResponse(null, { status: 204 })),

  http.post(`${B}/runs/:runId/review/careplan`, async ({ request }) => {
    const body = (await request.json()) as ReviewAction;
    // approve -> completed; request_changes -> back to running
    return HttpResponse.json(
      body.decision === "approve" ? runCompleted : runRunning,
      { status: 202 },
    );
  }),

  http.get(`${B}/careplans`, () => HttpResponse.json(carePlanSummaries)),
  http.get(`${B}/careplans/:id`, () => HttpResponse.json(carePlanDetail)),
  http.get(`${B}/status`, () => HttpResponse.json(systemHealth)),
];

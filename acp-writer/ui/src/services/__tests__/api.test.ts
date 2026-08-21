import { describe, it, expect } from "vitest";
import {
  createRun,
  listRuns,
  getRunDetail,
  submitReview,
  listCarePlans,
  getCarePlan,
  getSystemStatus,
} from "../api";

describe("api service", () => {
  it("createRun posts the ips bundle and returns runId", async () => {
    const res = await createRun({ resourceType: "Bundle" });
    expect(res.runId).toBe("run-123");
    expect(res.status).toBe("running");
  });

  it("listRuns returns summaries", async () => {
    const rows = await listRuns();
    expect(rows).toHaveLength(2);
    expect(rows[0].patientName).toBe("Ada Lovelace");
  });

  it("getRunDetail returns the run", async () => {
    const run = await getRunDetail("run-123");
    expect(run.status).toBe("running");
    expect(run.steps?.length).toBe(10);
  });

  it("submitReview approve returns a completed run", async () => {
    const run = await submitReview("run-review", { decision: "approve" });
    expect(run.status).toBe("completed");
  });

  it("listCarePlans and getCarePlan return view-models", async () => {
    expect((await listCarePlans())[0].patientName).toBe("Alan Turing");
    expect((await getCarePlan("cp-1")).view?.goals?.[0].id).toBe("g1");
  });

  it("getSystemStatus returns health", async () => {
    expect((await getSystemStatus()).decisionEngine?.available).toBe(true);
  });
});

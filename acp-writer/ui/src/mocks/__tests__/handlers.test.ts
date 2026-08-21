import { describe, it, expect } from "vitest";

describe("msw handlers", () => {
  it("serves run detail", async () => {
    // The server lifecycle is managed globally in src/setupTests.ts.
    const res = await fetch("/api/v1/runs/run-123");
    const body = await res.json();
    expect(body.runId).toBe("run-123");
    expect(body.status).toBe("running");
  });
});

import { describe, it, expect } from "vitest";
import { STEP_LABELS, toPipelineSteps } from "../steps";

describe("pipeline step mapping", () => {
  it("labels every StepKey", () => {
    expect(STEP_LABELS.execute_dmn).toBe("DMN decisions evaluated");
    expect(STEP_LABELS.review_careplan).toBe("Care-plan review");
  });

  it("maps contract steps to shared stepper steps with adapted status", () => {
    const steps = toPipelineSteps([
      { key: "scan_patient", status: "done" },
      { key: "execute_dmn", status: "active" },
      { key: "review_fhir", status: "skipped" },
      { key: "write_fhir", status: "error", detail: "boom" },
    ]);
    expect(steps[0]).toMatchObject({ id: "scan_patient", label: "Patient data scanned", status: "complete" });
    expect(steps[1].status).toBe("running");
    expect(steps[2].status).toBe("pending");
    expect(steps[3]).toMatchObject({ status: "error", duration: "boom" });
  });
});

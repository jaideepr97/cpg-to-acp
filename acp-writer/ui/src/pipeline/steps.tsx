import type { ReactNode } from "react";
import type { PipelineStep as SharedPipelineStep, StepStatus as SharedStepStatus } from "@cpg-to-acp/ui-shared";
import {
  ClusterIcon,
  ListIcon,
  OutlinedFileAltIcon,
  SearchIcon,
} from "@patternfly/react-icons";
import type { RunPipelineStep, RunStepStatus, StepKey } from "@app/api/models";

// UI-owned label vocabulary. The contract says: UI maps key -> label/icon; do
// not hardcode the step list beyond this shared StepKey vocabulary.
export const STEP_LABELS: Record<StepKey, string> = {
  scan_patient: "Patient data scanned",
  resolve_guidelines: "Guidelines resolved",
  execute_dmn: "DMN decisions evaluated",
  retrieve_recommendations: "Recommendations retrieved",
  compose_plan: "Care plan composed",
  generate_bundle: "FHIR bundle generated",
  review_fhir: "Clinical (FHIR) review",
  review_careplan: "Care-plan review",
  write_fhir: "Written to FHIR server",
  done: "Done",
};

export const STEP_ICONS: Partial<Record<StepKey, ReactNode>> = {
  scan_patient: <SearchIcon />,
  resolve_guidelines: <ListIcon />,
  execute_dmn: <ClusterIcon />,
  generate_bundle: <OutlinedFileAltIcon />,
};

// Contract StepStatus (pending|active|done|error|skipped) -> shared stepper
// vocab (pending|running|complete|error). skipped renders as pending for now;
// aligning the shared enum is a coordinated follow-up.
const STATUS_MAP: Record<RunStepStatus, SharedStepStatus> = {
  pending: "pending",
  active: "running",
  done: "complete",
  error: "error",
  skipped: "pending",
};

export function toPipelineSteps(steps: RunPipelineStep[]): SharedPipelineStep[] {
  return steps.map((s) => ({
    id: s.key,
    label: STEP_LABELS[s.key] ?? s.key,
    status: STATUS_MAP[s.status ?? "pending"] ?? "pending",
    duration: s.detail,
  }));
}

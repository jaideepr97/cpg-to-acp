import { useEffect } from "react";
import {
  ProgressStep,
  ProgressStepper,
} from "@patternfly/react-core";

const PULSE_STYLE_ID = "pipeline-stepper-pulse";
const PULSE_CSS = `
@keyframes stepPulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.45; }
}
.pf-v6-c-progress-stepper__step--pulse .pf-v6-c-progress-stepper__step-icon {
  animation: stepPulse 1.8s ease-in-out infinite;
}
`;

function usePulseStyle() {
  useEffect(() => {
    if (document.getElementById(PULSE_STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = PULSE_STYLE_ID;
    style.textContent = PULSE_CSS;
    document.head.appendChild(style);
  }, []);
}

export type StepStatus = "pending" | "running" | "complete" | "error";

export interface PipelineStep {
  id: string;
  label: string;
  status: StepStatus;
  duration?: string;
}

export interface PipelineStepperProps {
  steps: PipelineStep[];
}

const statusToVariant: Record<StepStatus, "pending" | "info" | "success" | "danger"> = {
  pending: "pending",
  running: "info",
  complete: "success",
  error: "danger",
};

export function PipelineStepper({ steps }: PipelineStepperProps) {
  usePulseStyle();
  return (
    <ProgressStepper isVertical>
      {steps.map((step) => (
        <ProgressStep
          key={step.id}
          id={step.id}
          titleId={`${step.id}-title`}
          variant={statusToVariant[step.status]}
          isCurrent={step.status === "running"}
          description={step.duration}
          className={step.status === "running" ? "pf-v6-c-progress-stepper__step--pulse" : undefined}
        >
          {step.label}
        </ProgressStep>
      ))}
    </ProgressStepper>
  );
}

import {
  ProgressStep,
  ProgressStepper,
} from "@patternfly/react-core";

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
        >
          {step.label}
        </ProgressStep>
      ))}
    </ProgressStepper>
  );
}

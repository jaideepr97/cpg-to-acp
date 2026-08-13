import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PipelineStepper, type PipelineStep } from "../components/PipelineStepper";

describe("PipelineStepper", () => {
  const steps: PipelineStep[] = [
    { id: "scan", label: "Scan patient data", status: "complete", duration: "1.2s" },
    { id: "resolve", label: "Resolve guidelines", status: "running" },
    { id: "compose", label: "Compose care plan", status: "pending" },
  ];

  it("renders all step labels", () => {
    render(<PipelineStepper steps={steps} />);

    expect(screen.getByText("Scan patient data")).toBeInTheDocument();
    expect(screen.getByText("Resolve guidelines")).toBeInTheDocument();
    expect(screen.getByText("Compose care plan")).toBeInTheDocument();
  });

  it("displays duration when provided", () => {
    render(<PipelineStepper steps={steps} />);
    expect(screen.getByText("1.2s")).toBeInTheDocument();
  });

  it("renders an empty list without crashing", () => {
    const { container } = render(<PipelineStepper steps={[]} />);
    expect(container.querySelector(".pf-v6-c-progress-stepper")).toBeInTheDocument();
  });

  it("renders error status steps", () => {
    const errorSteps: PipelineStep[] = [
      { id: "fail", label: "Failed step", status: "error" },
    ];
    render(<PipelineStepper steps={errorSteps} />);
    expect(screen.getByText("Failed step")).toBeInTheDocument();
  });
});

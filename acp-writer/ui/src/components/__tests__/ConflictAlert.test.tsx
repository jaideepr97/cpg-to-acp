import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ConflictAlert } from "../ConflictAlert";

describe("ConflictAlert", () => {
  it("renders description with a severity-mapped variant", () => {
    const { container } = render(
      <ConflictAlert conflict={{ id: "c1", severity: "critical", description: "Renal dosing conflict" }} />,
    );
    expect(screen.getByText("Renal dosing conflict")).toBeInTheDocument();
    expect(container.querySelector(".pf-m-danger")).toBeTruthy();
  });

  it("defaults to a warning variant when severity is absent", () => {
    const { container } = render(
      <ConflictAlert conflict={{ id: "c2", description: "Overlapping recommendation" }} />,
    );
    expect(container.querySelector(".pf-m-warning")).toBeTruthy();
  });
});

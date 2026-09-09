import { describe, it, expect } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ConflictAlert, conflictCountLabel, orderConflicts } from "../ConflictAlert";

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

  it("varies the title by category", () => {
    render(
      <ConflictAlert
        conflict={{ id: "c3", category: "divergent_target", description: "Different BP targets" }}
      />,
    );
    expect(screen.getByText(/Conflicting goal targets/)).toBeInTheDocument();
  });

  it("uses the overlap title", () => {
    render(<ConflictAlert conflict={{ id: "c3b", category: "overlap", description: "x" }} />);
    expect(screen.getByText(/Overlapping activities/)).toBeInTheDocument();
  });

  it("falls back to a generic title for an unknown category", () => {
    render(<ConflictAlert conflict={{ id: "c4", description: "Something" }} />);
    expect(screen.getByText(/Recommendation conflict/)).toBeInTheDocument();
  });

  it("lists the source CPGs on a From line, de-duplicated", () => {
    render(
      <ConflictAlert
        conflict={{
          id: "c5",
          category: "contradiction",
          description: "Conflicting advice",
          sources: [
            { cpgId: "SYN-HTN-2026-001", recommendationId: "rec-1" },
            { cpgId: "SYN-HTN-2026-001", recommendationId: "rec-3" },
            { cpgId: "SYN-DM2-2026-001", recommendationId: "rec-2" },
          ],
        }}
      />,
    );
    expect(screen.getByText(/SYN-HTN-2026-001 · SYN-DM2-2026-001/)).toBeInTheDocument();
  });

  it("omits the From line when there are no sources", () => {
    render(<ConflictAlert conflict={{ id: "c7", description: "no sources" }} />);
    expect(screen.queryByText(/From:/)).not.toBeInTheDocument();
  });

  it("renders the analyst's suggested resolution when present", () => {
    render(
      <ConflictAlert
        conflict={{
          id: "c8",
          category: "overlap",
          description: "Two diet activities",
          suggestedResolution: "Combine the two dietary-counseling activities into one",
        }}
      />,
    );
    expect(screen.getByText(/Suggested:/)).toBeInTheDocument();
    expect(
      screen.getByText(/Combine the two dietary-counseling activities into one/),
    ).toBeInTheDocument();
  });

  it("omits the Suggested line when there is no suggestion", () => {
    render(<ConflictAlert conflict={{ id: "c9", description: "no suggestion" }} />);
    expect(screen.queryByText(/Suggested:/)).not.toBeInTheDocument();
  });

  it("renders a resolved conflict as a success record with its resolution", () => {
    render(
      <ConflictAlert
        conflict={{
          id: "c10",
          category: "overlap",
          status: "resolved",
          severity: "warning",
          description: "The prior overlapping diet activities were merged",
          suggestedResolution: "Combine the two diet activities",
          resolution: "Resolved as suggested — merged into one cardiometabolic diet activity",
        }}
      />,
    );
    // Title flips to Resolved:; success (green) variant, not severity warning.
    expect(screen.getByText(/Resolved: Overlapping activities/)).toBeInTheDocument();
    expect(document.querySelector(".pf-m-success")).toBeTruthy();
    expect(document.querySelector(".pf-m-warning")).toBeFalsy();
    // Compact: collapsed by default — body hidden until the row is expanded.
    expect(document.querySelector(".pf-m-expandable")).toBeTruthy();
    expect(screen.queryByText(/Resolution:/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /details/i }));
    expect(screen.getByText(/Resolution:/)).toBeInTheDocument();
    expect(screen.getByText(/merged into one cardiometabolic diet activity/)).toBeInTheDocument();
    expect(screen.queryByText(/Suggested:/)).not.toBeInTheDocument();
  });

  it("renders open conflicts expanded (not expandable)", () => {
    render(
      <ConflictAlert
        conflict={{ id: "c12", category: "overlap", description: "Two diet activities" }}
      />,
    );
    expect(document.querySelector(".pf-m-expandable")).toBeFalsy();
    expect(screen.getByText(/Two diet activities/)).toBeInTheDocument();
  });

  it("orders open conflicts before resolved ones", () => {
    const ordered = orderConflicts([
      { id: "r1", description: "d", status: "resolved" },
      { id: "o1", description: "d", status: "detected" },
      { id: "r2", description: "d", status: "acknowledged" },
      { id: "o2", description: "d" },
    ]);
    expect(ordered.map((c) => c.id)).toEqual(["o1", "o2", "r1", "r2"]);
  });

  it("labels an acknowledged conflict", () => {
    render(
      <ConflictAlert
        conflict={{ id: "c11", category: "contradiction", status: "acknowledged", description: "d" }}
      />,
    );
    expect(screen.getByText(/Acknowledged: Conflicting recommendations/)).toBeInTheDocument();
  });

  it("counts open vs resolved in the tab label", () => {
    expect(
      conflictCountLabel([
        { id: "a", description: "d", status: "detected" },
        { id: "b", description: "d", status: "resolved" },
        { id: "c", description: "d", status: "resolved" },
      ]),
    ).toBe("Conflicts (1 open · 2 resolved)");
    expect(
      conflictCountLabel([{ id: "a", description: "d" }]),
    ).toBe("Conflicts (1)");
  });
});

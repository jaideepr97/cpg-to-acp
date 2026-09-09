import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ActivityCard } from "../ActivityCard";

describe("ActivityCard", () => {
  it("reveals provenance fields when the section is expanded", () => {
    render(
      <ActivityCard
        activity={{
          id: "a1",
          description: "Metformin 500mg twice daily",
          dose: "500mg",
          route: "oral",
          frequency: "twice daily",
          specialty: "endocrinology",
          sourceCpg: "ada-2024",
          sourceRecommendationId: "rec-9",
          clinicalRationale: "First-line for T2DM.",
        }}
      />,
    );
    expect(screen.getByText("Metformin 500mg twice daily")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /provenance/i }));
    expect(screen.getByText("500mg · oral · twice daily")).toBeInTheDocument();
    expect(screen.getByText("endocrinology")).toBeInTheDocument();
    expect(screen.getByText("ada-2024")).toBeInTheDocument();
    expect(screen.getByText("rec-9")).toBeInTheDocument();
    expect(screen.getByText("First-line for T2DM.")).toBeInTheDocument();
  });

  it("renders legacy detail when no structured provenance is present", () => {
    render(
      <ActivityCard
        activity={{ id: "a2", description: "HbA1c recheck", detail: "in 3 months" }}
      />,
    );
    expect(screen.getByText("HbA1c recheck")).toBeInTheDocument();
    expect(screen.getByText("in 3 months")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /provenance/i })).not.toBeInTheDocument();
  });

  it("renders without any optional fields", () => {
    render(<ActivityCard activity={{ id: "a3", description: "Bare activity" }} />);
    expect(screen.getByText("Bare activity")).toBeInTheDocument();
  });
});

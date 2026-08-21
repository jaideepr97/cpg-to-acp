import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ActivityCard } from "../ActivityCard";

describe("ActivityCard", () => {
  it("renders description and detail", () => {
    render(
      <ActivityCard
        activity={{ id: "a1", description: "Metformin 500mg twice daily", goalId: "g1", detail: "Titrate over 4 weeks" }}
      />,
    );
    expect(screen.getByText("Metformin 500mg twice daily")).toBeInTheDocument();
    expect(screen.getByText("Titrate over 4 weeks")).toBeInTheDocument();
  });

  it("renders without optional detail", () => {
    render(<ActivityCard activity={{ id: "a2", description: "HbA1c recheck in 3 months" }} />);
    expect(screen.getByText("HbA1c recheck in 3 months")).toBeInTheDocument();
  });
});

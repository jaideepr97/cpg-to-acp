import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { GoalCard } from "../GoalCard";

describe("GoalCard", () => {
  it("renders description, rationale, and source", () => {
    render(
      <GoalCard
        goal={{ id: "g1", description: "Achieve HbA1c < 7%", rationale: "Per ADA 2024", sourceCpgId: "ada-2024" }}
      />,
    );
    expect(screen.getByText("Achieve HbA1c < 7%")).toBeInTheDocument();
    expect(screen.getByText("Per ADA 2024")).toBeInTheDocument();
    expect(screen.getByText("ada-2024")).toBeInTheDocument();
  });

  it("omits optional rows when absent", () => {
    render(<GoalCard goal={{ id: "g2", description: "Stop smoking" }} />);
    expect(screen.getByText("Stop smoking")).toBeInTheDocument();
    expect(screen.queryByText("Rationale")).not.toBeInTheDocument();
  });
});

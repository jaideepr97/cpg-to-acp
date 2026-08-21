import { describe, it, expect } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithRouter } from "@app/test/renderWithRouter";
import { CarePlanList } from "../CarePlanList";

describe("CarePlanList", () => {
  it("shows patientName and a parsed generatedAt (not 'Invalid Date')", async () => {
    renderWithRouter(<CarePlanList />);
    await waitFor(() => expect(screen.getByText("Alan Turing")).toBeInTheDocument());
    expect(screen.queryByText("Invalid Date")).not.toBeInTheDocument();
    expect(screen.queryByText("Patient/")).not.toBeInTheDocument();
  });
});

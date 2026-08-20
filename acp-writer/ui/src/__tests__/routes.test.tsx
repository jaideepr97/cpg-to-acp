import { describe, it, expect } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AppRoutes } from "@app/routes";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
    </MemoryRouter>,
  );
}

describe("AppRoutes", () => {
  it("routes /runs to the run list", async () => {
    renderAt("/runs");
    await waitFor(() => expect(screen.getByText("Runs")).toBeInTheDocument());
  });
  it("routes /careplans to the care plan list", async () => {
    renderAt("/careplans");
    await waitFor(() => expect(screen.getByText("Care Plans")).toBeInTheDocument());
  });
  it("routes /runs/:id to the run detail page", async () => {
    renderAt("/runs/run-123");
    await waitFor(() => expect(screen.getByText(/Care Plan Run/)).toBeInTheDocument());
  });
});

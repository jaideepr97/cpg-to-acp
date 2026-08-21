import { describe, it, expect } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithRouter } from "@app/test/renderWithRouter";
import { CarePlanDetail } from "../CarePlanDetail";

describe("CarePlanDetail", () => {
  it("renders patient name and goal/activity counts from the view-model", async () => {
    renderWithRouter(<CarePlanDetail />, {
      routePath: "/careplans/:id",
      initialPath: "/careplans/cp-1",
    });
    await waitFor(() => expect(screen.getByText(/Ada Lovelace/)).toBeInTheDocument());
    expect(screen.getByText(/Goals \(1\)/)).toBeInTheDocument();
    expect(screen.getByText(/Activities \(2\)/)).toBeInTheDocument();
    // read-only: no approve/reject buttons
    expect(screen.queryByRole("button", { name: /approve/i })).not.toBeInTheDocument();
  });
});

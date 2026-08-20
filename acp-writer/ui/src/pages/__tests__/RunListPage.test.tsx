import { describe, it, expect } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithRouter } from "@app/test/renderWithRouter";
import { RunListPage } from "../RunListPage";

describe("RunListPage", () => {
  it("lists runs with status and current step", async () => {
    renderWithRouter(<RunListPage />);
    await waitFor(() => expect(screen.getByText("Ada Lovelace")).toBeInTheDocument());
    expect(screen.getByText("running")).toBeInTheDocument();
    expect(screen.getByText("DMN decisions evaluated")).toBeInTheDocument();
  });
});

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReviewPanel } from "../ReviewPanel";
import { carePlanView } from "@app/mocks/fixtures";

describe("ReviewPanel", () => {
  it("submits an approve decision", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<ReviewPanel carePlan={carePlanView} onSubmit={onSubmit} />);
    await userEvent.click(screen.getByRole("button", { name: /approve/i }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ decision: "approve" }));
  });

  it("submits request_changes with a comment", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<ReviewPanel carePlan={carePlanView} onSubmit={onSubmit} />);
    await userEvent.click(screen.getByRole("button", { name: /request changes/i }));
    await userEvent.type(screen.getByLabelText(/overall comment/i), "Tighten the HbA1c target");
    await userEvent.click(screen.getByRole("button", { name: /submit changes/i }));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ decision: "request_changes", comment: "Tighten the HbA1c target" }),
    );
  });
});

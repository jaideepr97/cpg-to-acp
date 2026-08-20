import { describe, it, expect, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithRouter } from "@app/test/renderWithRouter";
import { IpsView } from "../IpsView";

// jsdom in this project does not implement Blob/File.prototype.text(), which
// IpsView's client-side IPS preview relies on. Polyfill it via FileReader so
// the upload path parses the bundle. Component code is unchanged.
if (typeof Blob.prototype.text !== "function") {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (Blob.prototype as any).text = function (this: Blob): Promise<string> {
    return new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as string);
      reader.onerror = () => reject(reader.error);
      reader.readAsText(this);
    });
  };
}

const navigateMock = vi.fn();
vi.mock("react-router-dom", async (orig) => ({
  ...(await orig<typeof import("react-router-dom")>()),
  useNavigate: () => navigateMock,
}));

describe("IpsView", () => {
  it("navigates to the run page after createRun", async () => {
    renderWithRouter(<IpsView />);
    const file = new File(
      [JSON.stringify({ resourceType: "Bundle", entry: [] })],
      "ips.json",
      { type: "application/json" },
    );
    // FileUpload renders a hidden file input
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, file);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /generate care plan/i })).toBeEnabled(),
    );
    await userEvent.click(screen.getByRole("button", { name: /generate care plan/i }));
    await waitFor(() => expect(navigateMock).toHaveBeenCalledWith("/runs/run-123"));
  });
});

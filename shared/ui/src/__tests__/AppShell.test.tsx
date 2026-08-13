import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "../components/ThemeProvider";
import { AppShell } from "../components/AppShell";

function renderShell(props?: { brandText?: string }) {
  const navItems = [
    { label: "Home", path: "/" },
    { label: "Plans", path: "/plans" },
  ];

  return render(
    <MemoryRouter initialEntries={["/"]}>
      <ThemeProvider>
        <AppShell navItems={navItems} brandText={props?.brandText}>
          <div data-testid="content">page content</div>
        </AppShell>
      </ThemeProvider>
    </MemoryRouter>,
  );
}

describe("AppShell", () => {
  it("renders brand text", () => {
    renderShell();
    expect(screen.getByText("CPG Care Plans")).toBeInTheDocument();
  });

  it("accepts custom brand text", () => {
    renderShell({ brandText: "My App" });
    expect(screen.getByText("My App")).toBeInTheDocument();
  });

  it("renders navigation items as links", () => {
    renderShell();
    expect(screen.getByText("Home")).toBeInTheDocument();
    expect(screen.getByText("Plans")).toBeInTheDocument();
  });

  it("renders children", () => {
    renderShell();
    expect(screen.getByTestId("content")).toHaveTextContent("page content");
  });

  it("has a theme toggle button", () => {
    renderShell();
    const toggle = screen.getByLabelText("Toggle theme");
    expect(toggle).toBeInTheDocument();
  });

  it("has a sidebar toggle button", () => {
    renderShell();
    const toggle = screen.getByLabelText("Toggle sidebar");
    expect(toggle).toBeInTheDocument();
    fireEvent.click(toggle);
  });
});

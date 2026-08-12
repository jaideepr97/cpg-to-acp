import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ThemeProvider, useTheme } from "../components/ThemeProvider";

function ThemeDisplay() {
  const { theme, toggleTheme } = useTheme();
  return (
    <div>
      <span data-testid="theme">{theme}</span>
      <button onClick={toggleTheme}>toggle</button>
    </div>
  );
}

describe("ThemeProvider", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.classList.remove("pf-v6-theme-dark");
  });

  it("defaults to light theme", () => {
    render(
      <ThemeProvider>
        <ThemeDisplay />
      </ThemeProvider>,
    );
    expect(screen.getByTestId("theme")).toHaveTextContent("light");
  });

  it("restores theme from localStorage", () => {
    localStorage.setItem("cpg-theme", "dark");
    render(
      <ThemeProvider>
        <ThemeDisplay />
      </ThemeProvider>,
    );
    expect(screen.getByTestId("theme")).toHaveTextContent("dark");
  });

  it("toggles between light and dark", () => {
    render(
      <ThemeProvider>
        <ThemeDisplay />
      </ThemeProvider>,
    );

    fireEvent.click(screen.getByText("toggle"));
    expect(screen.getByTestId("theme")).toHaveTextContent("dark");
    expect(localStorage.getItem("cpg-theme")).toBe("dark");

    fireEvent.click(screen.getByText("toggle"));
    expect(screen.getByTestId("theme")).toHaveTextContent("light");
    expect(localStorage.getItem("cpg-theme")).toBe("light");
  });

  it("applies dark class to document element", () => {
    render(
      <ThemeProvider>
        <ThemeDisplay />
      </ThemeProvider>,
    );

    fireEvent.click(screen.getByText("toggle"));
    expect(document.documentElement.classList.contains("pf-v6-theme-dark")).toBe(true);

    fireEvent.click(screen.getByText("toggle"));
    expect(document.documentElement.classList.contains("pf-v6-theme-dark")).toBe(false);
  });

  it("throws when useTheme is used outside provider", () => {
    expect(() => render(<ThemeDisplay />)).toThrow(
      "useTheme must be used within a ThemeProvider",
    );
  });
});

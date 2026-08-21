import type { ReactElement } from "react";
import { render } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

// Render `element` mounted at `routePath`, navigated to `initialPath`, so
// hooks like useParams resolve. Defaults render the element at "/".
export function renderWithRouter(
  element: ReactElement,
  { routePath = "/", initialPath = "/" } = {},
) {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path={routePath} element={element} />
      </Routes>
    </MemoryRouter>,
  );
}

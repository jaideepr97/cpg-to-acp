import { BrowserRouter } from "react-router-dom";
import { ThemeProvider, AppShell } from "@cpg-to-acp/ui-shared";
import {
  PlusCircleIcon,
  RunningIcon,
  ListIcon,
  MonitoringIcon,
} from "@patternfly/react-icons";
import { AppRoutes } from "./routes";

const navItems = [
  { label: "New Care Plan", path: "/", icon: <PlusCircleIcon /> },
  { label: "Runs", path: "/runs", icon: <RunningIcon /> },
  { label: "Care Plans", path: "/careplans", icon: <ListIcon /> },
  { label: "System Status", path: "/status", icon: <MonitoringIcon /> },
];

export function App() {
  return (
    <ThemeProvider>
      <BrowserRouter>
        <AppShell navItems={navItems} brandText="ACP Writer">
          <AppRoutes />
        </AppShell>
      </BrowserRouter>
    </ThemeProvider>
  );
}

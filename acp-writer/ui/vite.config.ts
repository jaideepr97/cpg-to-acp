import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    // Force a single copy of these so the file: shared/ui package and the app
    // share one react/react-router-dom instance. The shared package is a `file:`
    // link carrying its own node_modules (its own react + PatternFly); without
    // this, AppShell's useLocation() binds to a different Router context, and a
    // shared PatternFly component (PipelineStepper -> ProgressStep) hits a second
    // React copy -> "invalid hook call" in `npm run dev`. Mirrors vitest.config.ts.
    // Proper fix is npm workspaces (#123).
    dedupe: [
      "react",
      "react-dom",
      "react-router-dom",
      "@patternfly/react-core",
      "@patternfly/react-icons",
    ],
    alias: [
      { find: "@app", replacement: resolve(__dirname, "src") },
      { find: /^react$/, replacement: resolve(__dirname, "node_modules/react") },
      { find: /^react-dom$/, replacement: resolve(__dirname, "node_modules/react-dom") },
      { find: /^react\/jsx-runtime$/, replacement: resolve(__dirname, "node_modules/react/jsx-runtime") },
      { find: /^react\/jsx-dev-runtime$/, replacement: resolve(__dirname, "node_modules/react/jsx-dev-runtime") },
      { find: /^react-dom\/client$/, replacement: resolve(__dirname, "node_modules/react-dom/client") },
    ],
  },
  server: {
    port: 3001,
    proxy: {
      "/api": {
        target: "http://localhost:8082",
        changeOrigin: true,
      },
      "/health": {
        target: "http://localhost:8082",
        changeOrigin: true,
      },
    },
  },
});

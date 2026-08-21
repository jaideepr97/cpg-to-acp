import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { resolve } from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    dedupe: ["react", "react-dom", "react-router-dom", "@patternfly/react-core", "@patternfly/react-icons"],
    // The shared `@cpg-to-acp/ui-shared` package is a `file:` link that carries
    // its own node_modules. Its transitive PatternFly (CJS) does `require("react")`,
    // which resolves to `shared/ui/node_modules/react` — a SECOND React whose
    // hook dispatcher is null under react-dom, crashing any shared PatternFly
    // component (e.g. PipelineStepper -> ProgressStep) with "invalid hook call".
    // `dedupe` collapses the shared package's own ESM react import but not the
    // externalized CJS transitive require, so force every react/react-dom
    // specifier to the app's single copy. Proper fix is npm workspaces (#123).
    alias: [
      { find: "@app", replacement: resolve(__dirname, "src") },
      { find: /^react$/, replacement: resolve(__dirname, "node_modules/react") },
      { find: /^react-dom$/, replacement: resolve(__dirname, "node_modules/react-dom") },
      { find: /^react\/jsx-runtime$/, replacement: resolve(__dirname, "node_modules/react/jsx-runtime") },
      { find: /^react\/jsx-dev-runtime$/, replacement: resolve(__dirname, "node_modules/react/jsx-dev-runtime") },
      { find: /^react-dom\/client$/, replacement: resolve(__dirname, "node_modules/react-dom/client") },
    ],
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/setupTests.ts"],
    server: {
      deps: {
        // Inline the shared package + PatternFly so vite transforms them and the
        // react/react-dom aliases above apply to their (CJS) imports too. Without
        // this, the externalized transitive `require("react")` resolves to the
        // shared package's own React copy -> "invalid hook call". See #123.
        inline: ["@cpg-to-acp/ui-shared", /@patternfly\//],
      },
    },
  },
});

# Spike A: UI Technology & Design System

**Phase:** 4 | **Status:** Complete | **Date:** 2026-07-23

## Decision

**[PatternFly 6](https://www.patternfly.org/) + React + TypeScript + Vite.**

This is not a choice — it's a constraint. PatternFly is Red Hat's design system, used by all Red Hat AI products including the OpenShift console. Deviating would look out of place alongside other Red Hat UIs.

> **Important:** The UI must never display the Red Hat logo or name. PatternFly is designed for white-labeling — components are styled by the design system, not branded to Red Hat. It is ok for things to look like OpenShift and other Red Hat products; they just need to not include the name or logo.

## Technology Stack

| Layer | Technology | Why |
|---|---|---|
| **Design system** | [PatternFly 6](https://www.patternfly.org/) | Red Hat standard. PF6 is exclusive in OpenShift 4.22+. |
| **Framework** | React 19 | PF6 supports React 17, 18, 19. Use latest. |
| **Language** | TypeScript | PF React components are written in TypeScript. Type safety for FHIR data structures. |
| **Build tool** | Vite | Fast HMR, standard for new React projects. The official PF seed uses webpack, but PF packages work fine with Vite — just `npm install @patternfly/react-core`. |
| **AI components** | [@patternfly/chatbot](https://github.com/patternfly/chatbot) | PF6 AI chatbot extension — message display, tool call visualization, deep thinking display. Useful for showing LLM reasoning in cpg-ingester (classification review, DMN creation) and acp-writer (plan composition, FHIR review). |
| **Charts** | @patternfly/react-charts | If needed for DMN visualization or care plan dashboards. |
| **Containerization** | Nginx serving static SPA | Same pattern as current UI pods. No SSR needed. |

## Key Packages

```bash
# Core
npm install @patternfly/react-core @patternfly/react-icons @patternfly/react-table

# AI chatbot
npm install @patternfly/chatbot

# Charts (if needed)
npm install @patternfly/react-charts

# FHIR
npm install fhir-kit-client  # or similar FHIR R4 client
```

## Project Structure

```
cpg-ingester/ui/           # cpg-ingester React app
├── src/
│   ├── App.tsx
│   ├── components/        # shared components
│   ├── pages/             # route-based pages
│   └── services/          # API clients
├── package.json
├── vite.config.ts
└── Dockerfile

acp-writer/ui/             # acp-writer React app
├── src/
│   ├── App.tsx
│   ├── components/
│   ├── pages/
│   └── services/
├── package.json
├── vite.config.ts
└── Dockerfile
```

Two separate React apps (not a monorepo). Each deploys as its own pod, consistent with the existing pod-split architecture.

## PatternFly AI Chatbot — Fit for This Project

The [@patternfly/chatbot](https://www.patternfly.org/patternfly-ai/chatbot/about-chatbot/) extension provides components that map directly to our pipeline's review interactions:

| PF Chatbot Feature | Our Use Case |
|---|---|
| AI-labeled messages | Show LLM-generated content clearly marked as AI |
| Tool call display | Show which MCP tools were called during pipeline execution |
| Deep thinking display | Show LLM reasoning during plan composition and FHIR review |
| Message editing | Clinician corrections to recommendations or care plan activities |
| Code blocks | Display DMN XML, FHIR JSON |
| Loading animation | Pipeline step progress |

This is more appropriate than building a custom status dashboard — the pipeline IS a conversation between the clinician and AI agents.

## What NOT to Use

- **Next.js** — SSR adds complexity we don't need. The UIs are internal tools, not public-facing SEO-optimized sites.
- **Django/Jinja** — current approach, being replaced. Python templating doesn't match the Red Hat AI ecosystem.
- **Angular** — not used in the Red Hat AI ecosystem.
- **Separate design system** — must use PatternFly. No Material UI, Ant Design, etc.

## Starter Template

Use `npm create vite@latest` with React + TypeScript template, then install PatternFly packages manually. The official [patternfly-react-seed](https://github.com/patternfly/patternfly-react-seed) uses webpack — starting fresh with Vite is cleaner.

```bash
npm create vite@latest cpg-ingester-ui -- --template react-ts
cd cpg-ingester-ui
npm install @patternfly/react-core @patternfly/react-icons @patternfly/react-table @patternfly/chatbot
```

## References

- [PatternFly 6](https://www.patternfly.org/) — design system
- [PatternFly React Seed](https://github.com/patternfly/patternfly-react-seed) — official starter (webpack)
- [PatternFly Chatbot](https://github.com/patternfly/chatbot) — AI chatbot extension
- [OpenShift 4.22 Plugin Guide](https://developers.redhat.com/articles/2026/07/14/red-hat-openshift-4-22-what-dynamic-plugin-developers-need-know) — PF6 exclusive
- [PatternFly Release Highlights](https://www.patternfly.org/get-started/release-highlights/) — React 19, AI components

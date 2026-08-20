import { Alert, type AlertProps } from "@patternfly/react-core";
import type { PlanConflict } from "@app/api/models";

const severityToVariant: Record<string, AlertProps["variant"]> = {
  info: "info",
  warning: "warning",
  critical: "danger",
};

export function ConflictAlert({ conflict }: { conflict: PlanConflict }) {
  const variant = severityToVariant[conflict.severity ?? "warning"] ?? "warning";
  return (
    <Alert variant={variant} isInline title="Recommendation conflict">
      <p>{conflict.description}</p>
    </Alert>
  );
}

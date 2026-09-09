import { Alert, type AlertProps } from "@patternfly/react-core";
import type { PlanConflict } from "@app/api/models";

const severityToVariant: Record<string, AlertProps["variant"]> = {
  info: "info",
  warning: "warning",
  critical: "danger",
};

const categoryToTitle: Record<string, string> = {
  overlap: "Overlapping activities — consider combining",
  contradiction: "Conflicting recommendations",
  divergent_target: "Conflicting goal targets",
  divergent_schedule: "Conflicting schedules",
  other: "Recommendation conflict",
};

const isClosed = (c: PlanConflict) => c.status === "resolved" || c.status === "acknowledged";

export function ConflictAlert({ conflict }: { conflict: PlanConflict }) {
  const baseTitle = categoryToTitle[conflict.category ?? "other"] ?? "Recommendation conflict";
  // A resolved/acknowledged conflict is a RECORD, not an open problem (issue
  // #169 F18 UX): render it as a compact success row, collapsed by default and
  // expandable for review — open conflicts keep their full-size prominence.
  const closed = isClosed(conflict);
  const variant: AlertProps["variant"] = closed
    ? "success"
    : (severityToVariant[conflict.severity ?? "warning"] ?? "warning");
  const title = conflict.status === "resolved"
    ? `Resolved: ${baseTitle}`
    : conflict.status === "acknowledged"
      ? `Acknowledged: ${baseTitle}`
      : baseTitle;
  // De-duplicate source CPGs for the "From:" line (multiple recs may cite one CPG).
  const cpgs = Array.from(new Set((conflict.sources ?? []).map((s) => s.cpgId)));

  return (
    <Alert variant={variant} isInline isExpandable={closed} title={title}>
      <p>{conflict.description}</p>
      {closed && conflict.resolution && (
        <p>
          <b>Resolution:</b> {conflict.resolution}
        </p>
      )}
      {!closed && conflict.suggestedResolution && (
        <p>
          <b>Suggested:</b> {conflict.suggestedResolution}
        </p>
      )}
      {cpgs.length > 0 && (
        <p>
          <b>From:</b> {cpgs.join(" · ")}
        </p>
      )}
    </Alert>
  );
}

/** Open conflicts first (full prominence), resolved/acknowledged records after
 * (compact, collapsed). Stable within each group. */
export function orderConflicts(conflicts: PlanConflict[]): PlanConflict[] {
  return [...conflicts.filter((c) => !isClosed(c)), ...conflicts.filter(isClosed)];
}

/** Tab/summary label: "Conflicts (2 open · 3 resolved)" once anything is
 * resolved/acknowledged, plain count otherwise. */
export function conflictCountLabel(conflicts: PlanConflict[]): string {
  const open = conflicts.filter((c) => !isClosed(c)).length;
  const closed = conflicts.length - open;
  return closed > 0 ? `Conflicts (${open} open · ${closed} resolved)` : `Conflicts (${conflicts.length})`;
}

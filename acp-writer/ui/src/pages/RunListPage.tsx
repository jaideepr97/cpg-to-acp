import { useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Button, Label, PageSection, Title } from "@patternfly/react-core";
import { Table, Tbody, Td, Th, Thead, Tr } from "@patternfly/react-table";
import { useAdaptivePolling } from "@cpg-to-acp/ui-shared";
import type { RunSummary } from "@app/api/models";
import { listRuns } from "@app/services/api";
import { STEP_LABELS } from "@app/pipeline/steps";

const statusColor: Record<string, "blue" | "green" | "red" | "grey"> = {
  running: "blue",
  awaiting_careplan_review: "orange" as "blue",
  completed: "green",
  failed: "red",
  cancelled: "grey",
};

export function RunListPage() {
  const navigate = useNavigate();
  const fetcher = useCallback(() => listRuns(), []);
  const { data: runs } = useAdaptivePolling<RunSummary[]>({
    fetcher,
    isComplete: () => true,
  });

  return (
    <PageSection>
      <Title headingLevel="h1">Runs</Title>
      <Table aria-label="Runs">
        <Thead>
          <Tr>
            <Th>Patient</Th>
            <Th>Status</Th>
            <Th>Current step</Th>
            <Th>Actions</Th>
          </Tr>
        </Thead>
        <Tbody>
          {(runs ?? []).map((run) => (
            <Tr key={run.runId}>
              <Td>{run.patientName ?? run.patientReference ?? "Unknown patient"}</Td>
              <Td>
                <Label color={statusColor[run.status] ?? "blue"}>{run.status}</Label>
              </Td>
              <Td>{(run.currentSteps ?? []).map((k) => STEP_LABELS[k] ?? k).join(", ") || "—"}</Td>
              <Td>
                <Button variant="link" onClick={() => navigate(`/runs/${run.runId}`)}>
                  View
                </Button>
              </Td>
            </Tr>
          ))}
          {runs && runs.length === 0 && (
            <Tr>
              <Td colSpan={4}>No runs yet.</Td>
            </Tr>
          )}
        </Tbody>
      </Table>
    </PageSection>
  );
}

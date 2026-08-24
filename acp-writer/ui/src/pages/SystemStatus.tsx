import { useCallback } from "react";
import {
  DescriptionList,
  DescriptionListDescription,
  DescriptionListGroup,
  DescriptionListTerm,
  Label,
  PageSection,
  Title,
} from "@patternfly/react-core";
import {
  Table,
  Thead,
  Tbody,
  Tr,
  Th,
  Td,
} from "@patternfly/react-table";
import { useAdaptivePolling } from "@cpg-to-acp/ui-shared";
import type { SystemHealth } from "@app/api/models";
import { getSystemStatus } from "@app/services/api";

export function SystemStatus() {
  const fetcher = useCallback(() => getSystemStatus(), []);
  const { data: status, error } = useAdaptivePolling<SystemHealth>({
    fetcher,
    isComplete: () => true,
  });

  const cpgs = status?.knowledgeBase?.cpgs ?? [];
  const decisions = status?.decisionEngine?.decisions ?? [];

  return (
    <PageSection>
      <Title headingLevel="h1">System Status</Title>
      {error && <p>Failed to load status.</p>}
      {status && (
        <>
          <DescriptionList isHorizontal>
            <DescriptionListGroup>
              <DescriptionListTerm>Version</DescriptionListTerm>
              <DescriptionListDescription>{status.version}</DescriptionListDescription>
            </DescriptionListGroup>
            <DescriptionListGroup>
              <DescriptionListTerm>Decision engine</DescriptionListTerm>
              <DescriptionListDescription>
                <Label color={status.decisionEngine?.available ? "green" : "red"}>
                  {status.decisionEngine?.available ? "available" : "unavailable"}
                </Label>{" "}
                {decisions.length} decisions deployed
              </DescriptionListDescription>
            </DescriptionListGroup>
            <DescriptionListGroup>
              <DescriptionListTerm>Knowledge base</DescriptionListTerm>
              <DescriptionListDescription>
                <Label color={status.knowledgeBase?.available ? "green" : "red"}>
                  {status.knowledgeBase?.available ? "available" : "unavailable"}
                </Label>{" "}
                {cpgs.length} guidelines,{" "}
                {status.knowledgeBase?.recommendations ?? 0} recommendations
              </DescriptionListDescription>
            </DescriptionListGroup>
          </DescriptionList>

          {cpgs.length > 0 && (
            <>
              <Title headingLevel="h2" style={{ marginTop: "1.5rem" }}>
                Clinical Practice Guidelines
              </Title>
              <Table aria-label="Clinical Practice Guidelines" variant="compact">
                <Thead>
                  <Tr>
                    <Th>Title</Th>
                    <Th>CPG ID</Th>
                    <Th>Version</Th>
                    <Th>Issuing body</Th>
                  </Tr>
                </Thead>
                <Tbody>
                  {cpgs.map((cpg) => (
                    <Tr key={cpg.cpgId}>
                      <Td>{cpg.title}</Td>
                      <Td>
                        <code>{cpg.cpgId}</code>
                      </Td>
                      <Td>{cpg.version ?? "—"}</Td>
                      <Td>{cpg.issuingBody ?? "—"}</Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>
            </>
          )}

          {decisions.length > 0 && (
            <>
              <Title headingLevel="h2" style={{ marginTop: "1.5rem" }}>
                Decisions
              </Title>
              <Table aria-label="Decision models" variant="compact">
                <Thead>
                  <Tr>
                    <Th>Name</Th>
                    <Th>ID</Th>
                    <Th>Source CPG</Th>
                  </Tr>
                </Thead>
                <Tbody>
                  {decisions.map((d) => (
                    <Tr key={d.id}>
                      <Td>{d.name}</Td>
                      <Td>
                        <code>{d.id}</code>
                      </Td>
                      <Td>{d.sourceCpg ?? "—"}</Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>
            </>
          )}
        </>
      )}
    </PageSection>
  );
}

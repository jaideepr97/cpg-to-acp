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
import { useAdaptivePolling } from "@cpg-to-acp/ui-shared";
import type { SystemHealth } from "@app/api/models";
import { getSystemStatus } from "@app/services/api";

export function SystemStatus() {
  const fetcher = useCallback(() => getSystemStatus(), []);
  const { data: status, error } = useAdaptivePolling<SystemHealth>({
    fetcher,
    isComplete: () => true,
  });

  return (
    <PageSection>
      <Title headingLevel="h1">System Status</Title>
      {error && <p>Failed to load status.</p>}
      {status && (
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
              {status.decisionEngine?.modelsDeployed ?? 0} models deployed
            </DescriptionListDescription>
          </DescriptionListGroup>
          <DescriptionListGroup>
            <DescriptionListTerm>Knowledge base</DescriptionListTerm>
            <DescriptionListDescription>
              <Label color={status.knowledgeBase?.available ? "green" : "red"}>
                {status.knowledgeBase?.available ? "available" : "unavailable"}
              </Label>{" "}
              {status.knowledgeBase?.guidelines ?? 0} guidelines,{" "}
              {status.knowledgeBase?.recommendations ?? 0} recommendations
            </DescriptionListDescription>
          </DescriptionListGroup>
        </DescriptionList>
      )}
    </PageSection>
  );
}

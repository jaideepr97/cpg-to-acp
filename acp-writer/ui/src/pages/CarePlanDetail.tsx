import { useCallback, useState } from "react";
import { useParams } from "react-router-dom";
import {
  Label,
  PageSection,
  Stack,
  StackItem,
  Tab,
  Tabs,
  TabTitleText,
  Title,
} from "@patternfly/react-core";
import { useAdaptivePolling } from "@cpg-to-acp/ui-shared";
import type { CarePlanDetail as CarePlanDetailModel } from "@app/api/models";
import { getCarePlan } from "@app/services/api";
import { GoalCard } from "@app/components/GoalCard";
import { ActivityCard } from "@app/components/ActivityCard";
import { ConflictAlert } from "@app/components/ConflictAlert";
import { FhirJsonViewer } from "@app/components/FhirJsonViewer";

const statusColor: Record<string, "blue" | "green" | "red"> = {
  draft: "blue",
  active: "green",
  "entered-in-error": "red",
};

export function CarePlanDetail() {
  const { id } = useParams<{ id: string }>();
  const [activeTab, setActiveTab] = useState(0);
  const fetcher = useCallback(() => getCarePlan(id!), [id]);
  const { data: plan } = useAdaptivePolling<CarePlanDetailModel>({
    fetcher,
    isComplete: () => true,
    enabled: !!id,
  });

  if (!plan) {
    return (
      <PageSection>
        <Title headingLevel="h1">Loading care plan…</Title>
      </PageSection>
    );
  }

  const view = plan.view ?? {};
  const goals = view.goals ?? [];
  const activities = view.activities ?? [];
  const conflicts = view.conflicts ?? [];

  return (
    <>
      <PageSection>
        <Title headingLevel="h1">Care Plan</Title>
        <div>
          Patient: {plan.patient?.name ?? plan.patientName ?? "Unknown patient"}{" "}
          <Label color={statusColor[plan.status] ?? "blue"}>{plan.status}</Label>
        </div>
      </PageSection>
      <PageSection isFilled>
        <Tabs activeKey={activeTab} onSelect={(_e, key) => setActiveTab(key as number)}>
          <Tab eventKey={0} title={<TabTitleText>Goals ({goals.length})</TabTitleText>}>
            <Stack hasGutter style={{ paddingTop: "1rem" }}>
              {goals.length === 0 ? (
                <StackItem><p>No goals defined.</p></StackItem>
              ) : (
                goals.map((g) => <StackItem key={g.id}><GoalCard goal={g} /></StackItem>)
              )}
            </Stack>
          </Tab>
          <Tab eventKey={1} title={<TabTitleText>Activities ({activities.length})</TabTitleText>}>
            <Stack hasGutter style={{ paddingTop: "1rem" }}>
              {activities.length === 0 ? (
                <StackItem><p>No activities defined.</p></StackItem>
              ) : (
                activities.map((a) => <StackItem key={a.id}><ActivityCard activity={a} /></StackItem>)
              )}
            </Stack>
          </Tab>
          <Tab eventKey={2} title={<TabTitleText>Conflicts ({conflicts.length})</TabTitleText>}>
            <Stack hasGutter style={{ paddingTop: "1rem" }}>
              {conflicts.length === 0 ? (
                <StackItem><p>No conflicts detected.</p></StackItem>
              ) : (
                conflicts.map((c) => <StackItem key={c.id}><ConflictAlert conflict={c} /></StackItem>)
              )}
            </Stack>
          </Tab>
        </Tabs>
        {view.fhirBundle && (
          <div style={{ marginTop: "1rem" }}>
            <FhirJsonViewer json={view.fhirBundle} title="View FHIR Bundle JSON" />
          </div>
        )}
      </PageSection>
    </>
  );
}

import {
  Card,
  CardBody,
  CardTitle,
  DescriptionList,
  DescriptionListDescription,
  DescriptionListGroup,
  DescriptionListTerm,
} from "@patternfly/react-core";
import type { PlanGoal } from "@app/api/models";

export function GoalCard({ goal }: { goal: PlanGoal }) {
  return (
    <Card isCompact>
      <CardTitle>{goal.description}</CardTitle>
      {(goal.rationale || goal.sourceCpgId) && (
        <CardBody>
          <DescriptionList isHorizontal isCompact>
            {goal.rationale && (
              <DescriptionListGroup>
                <DescriptionListTerm>Rationale</DescriptionListTerm>
                <DescriptionListDescription>{goal.rationale}</DescriptionListDescription>
              </DescriptionListGroup>
            )}
            {goal.sourceCpgId && (
              <DescriptionListGroup>
                <DescriptionListTerm>Source guideline</DescriptionListTerm>
                <DescriptionListDescription>{goal.sourceCpgId}</DescriptionListDescription>
              </DescriptionListGroup>
            )}
          </DescriptionList>
        </CardBody>
      )}
    </Card>
  );
}

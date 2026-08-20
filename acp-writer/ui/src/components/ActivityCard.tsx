import { Card, CardBody, CardTitle } from "@patternfly/react-core";
import { RunningIcon } from "@patternfly/react-icons";
import type { PlanActivity } from "@app/api/models";

export function ActivityCard({ activity }: { activity: PlanActivity }) {
  return (
    <Card isCompact>
      <CardTitle>
        <span style={{ marginRight: "0.5rem" }}>
          <RunningIcon />
        </span>
        {activity.description}
      </CardTitle>
      {activity.detail && <CardBody>{activity.detail}</CardBody>}
    </Card>
  );
}

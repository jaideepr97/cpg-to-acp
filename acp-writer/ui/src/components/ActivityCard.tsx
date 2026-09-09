import {
  Card,
  CardBody,
  CardTitle,
  DescriptionList,
  DescriptionListDescription,
  DescriptionListGroup,
  DescriptionListTerm,
  ExpandableSection,
} from "@patternfly/react-core";
import { RunningIcon } from "@patternfly/react-icons";
import type { PlanActivity } from "@app/api/models";
import { provenanceListStyle } from "./provenanceStyle";

export function ActivityCard({ activity }: { activity: PlanActivity }) {
  const dosing = [activity.dose, activity.route, activity.frequency]
    .filter(Boolean)
    .join(" · ");
  const hasProvenance =
    dosing ||
    activity.specialty ||
    activity.sourceCpg ||
    activity.sourceRecommendationId ||
    activity.clinicalRationale;

  return (
    <Card isCompact>
      <CardTitle>
        <span style={{ marginRight: "0.5rem" }}>
          <RunningIcon />
        </span>
        {activity.description}
      </CardTitle>
      {hasProvenance ? (
        <CardBody>
          <ExpandableSection toggleText="Provenance" isIndented>
            <DescriptionList isHorizontal isCompact style={provenanceListStyle}>
              {dosing && (
                <DescriptionListGroup>
                  <DescriptionListTerm>Dosing</DescriptionListTerm>
                  <DescriptionListDescription>{dosing}</DescriptionListDescription>
                </DescriptionListGroup>
              )}
              {activity.specialty && (
                <DescriptionListGroup>
                  <DescriptionListTerm>Specialty</DescriptionListTerm>
                  <DescriptionListDescription>{activity.specialty}</DescriptionListDescription>
                </DescriptionListGroup>
              )}
              {activity.sourceCpg && (
                <DescriptionListGroup>
                  <DescriptionListTerm>Source guideline</DescriptionListTerm>
                  <DescriptionListDescription>{activity.sourceCpg}</DescriptionListDescription>
                </DescriptionListGroup>
              )}
              {activity.sourceRecommendationId && (
                <DescriptionListGroup>
                  <DescriptionListTerm>Source recommendation</DescriptionListTerm>
                  <DescriptionListDescription>{activity.sourceRecommendationId}</DescriptionListDescription>
                </DescriptionListGroup>
              )}
              {activity.clinicalRationale && (
                <DescriptionListGroup>
                  <DescriptionListTerm>Clinical rationale</DescriptionListTerm>
                  <DescriptionListDescription>{activity.clinicalRationale}</DescriptionListDescription>
                </DescriptionListGroup>
              )}
            </DescriptionList>
          </ExpandableSection>
        </CardBody>
      ) : (
        activity.detail && <CardBody>{activity.detail}</CardBody>
      )}
    </Card>
  );
}

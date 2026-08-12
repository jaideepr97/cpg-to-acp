import {
  Button,
  Card,
  CardBody,
  CardTitle,
  Content,
  DescriptionList,
  DescriptionListDescription,
  DescriptionListGroup,
  DescriptionListTerm,
  Label,
} from '@patternfly/react-core';
import { Table, Tbody, Td, Th, Thead, Tr } from '@patternfly/react-table';
import type { ReviewFeedbackItem, RunDetail } from '../api/types';
import { ReviewActionBar } from '../components/ReviewActionBar';
import { useReviewGate } from '../hooks/useReviewGate';

interface ApprovalDeliveryPageProps {
  run: RunDetail;
}

export function ApprovalDeliveryPage({ run }: ApprovalDeliveryPageProps) {
  const review = useReviewGate(run);

  if (run.deliveryStatus) {
    const ds = run.deliveryStatus;
    return (
      <div style={{ marginTop: 16 }}>
        <Card>
          <CardTitle>Delivery Status</CardTitle>
          <CardBody>
            <Label color={ds.delivered ? 'green' : 'red'} style={{ marginBottom: 16 }}>
              {ds.delivered ? 'Delivered Successfully' : 'Delivery Failed'}
            </Label>
            <DescriptionList isCompact isHorizontal>
              <DescriptionListGroup>
                <DescriptionListTerm>Target</DescriptionListTerm>
                <DescriptionListDescription>{ds.acp_writer_url}</DescriptionListDescription>
              </DescriptionListGroup>
            </DescriptionList>

            <Table aria-label="Delivery results" style={{ marginTop: 16 }}>
              <Thead>
                <Tr>
                  <Th>Artifact</Th>
                  <Th>Status</Th>
                  <Th>Details</Th>
                </Tr>
              </Thead>
              <Tbody>
                {ds.results?.metadata && (
                  <Tr>
                    <Td>Guidelines Metadata</Td>
                    <Td>
                      <Label color={ds.results.metadata.status < 300 ? 'green' : 'red'} isCompact>
                        {ds.results.metadata.status}
                      </Label>
                    </Td>
                    <Td>{ds.results.metadata.cpg_id}</Td>
                  </Tr>
                )}
                {ds.results?.dmn_models?.map((model, i) => (
                  <Tr key={i}>
                    <Td>DMN Model</Td>
                    <Td>
                      <Label color={model.status < 300 ? 'green' : 'red'} isCompact>
                        {model.status}
                      </Label>
                    </Td>
                    <Td>{model.name}</Td>
                  </Tr>
                ))}
                {ds.results?.recommendations && (
                  <Tr>
                    <Td>Recommendations</Td>
                    <Td>
                      <Label color={ds.results.recommendations.status < 300 ? 'green' : 'red'} isCompact>
                        {ds.results.recommendations.status}
                      </Label>
                    </Td>
                    <Td>{ds.results.recommendations.count} recommendations</Td>
                  </Tr>
                )}
                {ds.results?.errors?.map((err, i) => (
                  <Tr key={`err-${i}`}>
                    <Td>Error</Td>
                    <Td><Label color="red" isCompact>Error</Label></Td>
                    <Td>{err}</Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          </CardBody>
        </Card>
      </div>
    );
  }

  const emptyFeedback = new Map<string, { itemType: ReviewFeedbackItem['itemType']; comment: string }>();

  return (
    <div style={{ marginTop: 16 }}>
      <Card>
        <CardTitle>Deliver to acp-writer</CardTitle>
        <CardBody>
          {run.metadata && (
            <DescriptionList isCompact isHorizontal style={{ marginBottom: 16 }}>
              <DescriptionListGroup>
                <DescriptionListTerm>CPG</DescriptionListTerm>
                <DescriptionListDescription>{run.metadata.title}</DescriptionListDescription>
              </DescriptionListGroup>
              {run.metadata.version && (
                <DescriptionListGroup>
                  <DescriptionListTerm>Version</DescriptionListTerm>
                  <DescriptionListDescription>{run.metadata.version}</DescriptionListDescription>
                </DescriptionListGroup>
              )}
            </DescriptionList>
          )}

          <Content component="p">The following artifacts will be delivered:</Content>
          <ul>
            <li>Guidelines metadata</li>
            {run.decisions && <li>{run.decisions.length} DMN decision model(s)</li>}
            {run.recommendations && <li>{run.recommendations.length} recommendation(s)</li>}
          </ul>

          {review.isReviewActive && review.gate === 'pre-delivery' ? (
            <ReviewActionBar
              onApprove={() => review.approveMutation.mutate()}
              onRequestChanges={(feedback, comment) =>
                review.requestChangesMutation.mutate({ feedback, overallComment: comment })
              }
              isApproving={review.approveMutation.isPending}
              isRequestingChanges={review.requestChangesMutation.isPending}
              error={review.approveMutation.error ?? review.requestChangesMutation.error}
              itemFeedback={emptyFeedback}
              reviewIteration={review.reviewIteration}
            />
          ) : (
            <Button variant="primary" isDisabled style={{ marginTop: 16 }}>
              Waiting for pipeline to reach delivery...
            </Button>
          )}
        </CardBody>
      </Card>
    </div>
  );
}

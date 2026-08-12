import {
  Card,
  CardBody,
  CardTitle,
  CodeBlock,
  CodeBlockCode,
  Content,
  DataList,
  DataListCell,
  DataListItem,
  DataListItemCells,
  DataListItemRow,
  ExpandableSection,
  Label,
  LabelGroup,
} from '@patternfly/react-core';
import { useCallback, useState } from 'react';
import type { ReviewFeedbackItem, RunDetail } from '../api/types';
import { FeedbackInput } from '../components/FeedbackInput';
import { ReviewActionBar } from '../components/ReviewActionBar';
import { useReviewGate } from '../hooks/useReviewGate';

interface DecisionReviewPageProps {
  run: RunDetail;
}

export function DecisionReviewPage({ run }: DecisionReviewPageProps) {
  const review = useReviewGate(run);
  const [expandedXml, setExpandedXml] = useState<Set<string>>(new Set());
  const [feedbackMap, setFeedbackMap] = useState<Map<string, { itemType: ReviewFeedbackItem['itemType']; comment: string }>>(new Map());

  const handleFeedbackChange = useCallback((itemId: string, comment: string) => {
    setFeedbackMap(prev => {
      const next = new Map(prev);
      if (comment) {
        next.set(itemId, { itemType: 'decision', comment });
      } else {
        next.delete(itemId);
      }
      return next;
    });
  }, []);

  if (!run.decisions || run.decisions.length === 0) {
    return (
      <Card style={{ marginTop: 16 }}>
        <CardBody>
          <Content component="p">No decision models available yet.</Content>
        </CardBody>
      </Card>
    );
  }

  return (
    <div style={{ marginTop: 16 }}>
      <Card>
        <CardTitle>
          Decision Models ({run.decisions.length})
          {review.reviewIteration > 1 && (
            <Label color="blue" isCompact style={{ marginLeft: 8 }}>
              Iteration {review.reviewIteration}
            </Label>
          )}
        </CardTitle>
        <CardBody>
          <DataList aria-label="Decision models">
            {run.decisions.map((decision, i) => {
              const key = decision.decision_model_summary?.id ?? `dmn-${i}`;
              const name = decision.decision_model_summary?.name ?? decision.item.name;
              const isXmlExpanded = expandedXml.has(key);

              return (
                <DataListItem key={key} aria-labelledby={`decision-${key}`}>
                  <DataListItemRow>
                    <DataListItemCells
                      dataListCells={[
                        <DataListCell key="name" width={2}>
                          <div>
                            <strong id={`decision-${key}`}>{name}</strong>
                            {decision.item.category && (
                              <Label color="blue" isCompact style={{ marginLeft: 8 }}>
                                {decision.item.category}
                              </Label>
                            )}
                          </div>
                          {decision.item.section && (
                            <Content component="small">
                              Source: {decision.item.section}
                            </Content>
                          )}
                        </DataListCell>,
                        <DataListCell key="io" width={3}>
                          {decision.decision_model_summary?.inputs && (
                            <div style={{ marginBottom: 4 }}>
                              <Content component="small">Inputs:</Content>{' '}
                              <LabelGroup>
                                {decision.decision_model_summary.inputs.map(v => (
                                  <Label key={v.name} isCompact>{v.name}: {v.type}</Label>
                                ))}
                              </LabelGroup>
                            </div>
                          )}
                          {decision.decision_model_summary?.outputs && (
                            <div>
                              <Content component="small">Outputs:</Content>{' '}
                              <LabelGroup>
                                {decision.decision_model_summary.outputs.map(v => (
                                  <Label key={v.name} isCompact color="green">{v.name}: {v.type}</Label>
                                ))}
                              </LabelGroup>
                            </div>
                          )}
                        </DataListCell>,
                      ]}
                    />
                  </DataListItemRow>
                  <div style={{ padding: '0 16px 16px' }}>
                    <ExpandableSection
                      toggleText={isXmlExpanded ? 'Hide DMN XML' : 'Show DMN XML'}
                      isExpanded={isXmlExpanded}
                      onToggle={() => {
                        setExpandedXml(prev => {
                          const next = new Set(prev);
                          if (next.has(key)) next.delete(key);
                          else next.add(key);
                          return next;
                        });
                      }}
                    >
                      <CodeBlock>
                        <CodeBlockCode>{decision.dmn_xml}</CodeBlockCode>
                      </CodeBlock>
                    </ExpandableSection>
                    {review.isReviewActive && review.gate === 'pre-delivery' && (
                      <FeedbackInput
                        itemId={key}
                        onFeedbackChange={handleFeedbackChange}
                        existingComment={feedbackMap.get(key)?.comment}
                      />
                    )}
                  </div>
                </DataListItem>
              );
            })}
          </DataList>
        </CardBody>
      </Card>

      {review.isReviewActive && review.gate === 'pre-delivery' && (
        <ReviewActionBar
          onApprove={() => review.approveMutation.mutate()}
          onRequestChanges={(feedback, comment) =>
            review.requestChangesMutation.mutate({ feedback, overallComment: comment })
          }
          isApproving={review.approveMutation.isPending}
          isRequestingChanges={review.requestChangesMutation.isPending}
          error={review.approveMutation.error ?? review.requestChangesMutation.error}
          itemFeedback={feedbackMap}
          reviewIteration={review.reviewIteration}
        />
      )}
    </div>
  );
}

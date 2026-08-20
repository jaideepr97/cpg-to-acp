import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Flex,
  FlexItem,
  PageSection,
  Stack,
  StackItem,
  Title,
} from "@patternfly/react-core";
import { PipelineStepper, useAdaptivePolling } from "@cpg-to-acp/ui-shared";
import type { RunDetail, ReviewAction } from "@app/api/models";
import { getRunDetail, submitReview } from "@app/services/api";
import { toPipelineSteps } from "@app/pipeline/steps";
import { ReviewPanel } from "@app/components/ReviewPanel";

export function RunDetailPage() {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const [refreshKey, setRefreshKey] = useState(0);

  // fetcher carries runId + refreshKey so submitting a review restarts polling
  // (the run goes back to `running` after request_changes). See #125 fix: a new
  // fetcher identity is the intended restart trigger.
  const fetcher = useCallback(
    () => getRunDetail(runId!),
    [runId, refreshKey],
  );
  const isComplete = useCallback((r: RunDetail) => r.status !== "running", []);
  const { data: run } = useAdaptivePolling<RunDetail>({
    fetcher,
    isComplete,
    enabled: !!runId,
  });

  const steps = useMemo(() => toPipelineSteps(run?.steps ?? []), [run]);

  // Navigate to the persisted plan once the run completes.
  useEffect(() => {
    if (run?.status === "completed" && run.careplanId) {
      navigate(`/careplans/${run.careplanId}`, { replace: true });
    }
  }, [run?.status, run?.careplanId, navigate]);

  const handleReview = async (action: ReviewAction) => {
    await submitReview(runId!, action);
    // Resume polling: request_changes -> back to running; approve -> terminal.
    setRefreshKey((k) => k + 1);
  };

  if (!run) {
    return (
      <PageSection>
        <Title headingLevel="h1">Loading run…</Title>
      </PageSection>
    );
  }

  return (
    <PageSection>
      <Flex direction={{ default: "column" }} gap={{ default: "gapLg" }}>
        <FlexItem>
          <Title headingLevel="h1">
            Care Plan Run{run.patient?.name ? ` — ${run.patient.name}` : ""}
          </Title>
          <p>Status: {run.status}</p>
        </FlexItem>
        <FlexItem>
          <Stack hasGutter>
            <StackItem>
              <Title headingLevel="h2">Pipeline</Title>
            </StackItem>
            <StackItem>
              <PipelineStepper steps={steps} />
            </StackItem>
          </Stack>
        </FlexItem>
        {run.awaitingReview === "careplan" && run.carePlan && (
          <FlexItem>
            <ReviewPanel
              carePlan={run.carePlan}
              reviewIteration={run.reviewIteration}
              previousFeedback={run.previousFeedback}
              onSubmit={handleReview}
            />
          </FlexItem>
        )}
        {run.status === "failed" && (
          <FlexItem>
            <p style={{ color: "var(--pf-t--global--color--status--danger--default)" }}>
              Run failed{run.error?.message ? `: ${run.error.message}` : "."}
            </p>
          </FlexItem>
        )}
      </Flex>
    </PageSection>
  );
}

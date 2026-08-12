import {
  Button,
  EmptyState,
  EmptyStateActions,
  EmptyStateBody,
  EmptyStateFooter,
  Label,
  PageSection,
  Skeleton,
  Title,
} from '@patternfly/react-core';
import { CubesIcon, RedoIcon } from '@patternfly/react-icons';
import { Table, Tbody, Td, Th, Thead, Tr } from '@patternfly/react-table';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router';

import { api } from '../api/client';
import type { RunStatus } from '../api/types';
import { useRuns } from '../hooks/useRuns';

const STATUS_LABEL: Record<RunStatus, { text: string; color: 'blue' | 'teal' | 'orange' | 'green' | 'red' | 'purple' }> = {
  parsing: { text: 'Parsing', color: 'blue' },
  analyzing: { text: 'Analyzing', color: 'blue' },
  awaiting_manifest_review: { text: 'Awaiting Review', color: 'orange' },
  generating: { text: 'Generating', color: 'teal' },
  awaiting_artifact_review: { text: 'Awaiting Review', color: 'orange' },
  assembling: { text: 'Assembling', color: 'purple' },
  delivering: { text: 'Delivering', color: 'purple' },
  completed: { text: 'Complete', color: 'green' },
  failed: { text: 'Failed', color: 'red' },
};

export function DashboardPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: runs, isLoading, isError } = useRuns();

  const rerunMutation = useMutation({
    mutationFn: (runId: string) => api.rerunPipeline(runId),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['runs'] });
      navigate(`/runs/${data.runId}`);
    },
  });

  return (
    <>
      <PageSection>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Title headingLevel="h1">Pipeline Runs</Title>
          <Button variant="primary" onClick={() => navigate('/upload')}>
            Upload CPG
          </Button>
        </div>
      </PageSection>
      <PageSection>
        {isLoading ? (
          <>
            <Skeleton screenreaderText="Loading runs" width="100%" height="32px" style={{ marginBottom: 8 }} />
            <Skeleton width="100%" height="32px" style={{ marginBottom: 8 }} />
            <Skeleton width="100%" height="32px" style={{ marginBottom: 8 }} />
          </>
        ) : isError ? (
          <EmptyState
            headingLevel="h2"
            titleText="Unable to load runs"
            icon={CubesIcon}
          >
            <EmptyStateBody>
              The backend is not reachable. Start the BFF service and try again.
            </EmptyStateBody>
          </EmptyState>
        ) : !runs || runs.length === 0 ? (
          <EmptyState
            headingLevel="h2"
            titleText="No pipeline runs yet"
            icon={CubesIcon}
          >
            <EmptyStateBody>
              Upload a Clinical Practice Guideline PDF to start the ingestion pipeline.
            </EmptyStateBody>
            <EmptyStateFooter>
              <EmptyStateActions>
                <Button variant="primary" onClick={() => navigate('/upload')}>
                  Upload CPG
                </Button>
              </EmptyStateActions>
            </EmptyStateFooter>
          </EmptyState>
        ) : (
          <Table aria-label="Pipeline runs">
            <Thead>
              <Tr>
                <Th>CPG Name</Th>
                <Th>Uploaded</Th>
                <Th>Status</Th>
                <Th>Current Step</Th>
                <Th />
              </Tr>
            </Thead>
            <Tbody>
              {runs.map((run) => {
                const label = STATUS_LABEL[run.status] ?? { text: run.status, color: 'blue' as const };
                return (
                  <Tr
                    key={run.id}
                    isClickable
                    onRowClick={() => navigate(`/runs/${run.id}`)}
                  >
                    <Td dataLabel="CPG Name">{run.cpgName}</Td>
                    <Td dataLabel="Uploaded">
                      {new Date(run.createdAt).toLocaleString()}
                    </Td>
                    <Td dataLabel="Status">
                      <Label color={label.color}>{label.text}</Label>
                    </Td>
                    <Td dataLabel="Current Step">{run.currentStep}</Td>
                    <Td isActionCell>
                      {(run.status === 'completed' || run.status === 'failed') && (
                        <Button
                          variant="plain"
                          aria-label="Rerun pipeline"
                          onClick={(e) => {
                            e.stopPropagation();
                            rerunMutation.mutate(run.id);
                          }}
                          isDisabled={rerunMutation.isPending}
                        >
                          <RedoIcon />
                        </Button>
                      )}
                    </Td>
                  </Tr>
                );
              })}
            </Tbody>
          </Table>
        )}
      </PageSection>
    </>
  );
}

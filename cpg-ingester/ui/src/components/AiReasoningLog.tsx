import {
  Content,
  ExpandableSection,
  Label,
} from '@patternfly/react-core';
import { useState } from 'react';
import type { PipelineStep } from '../api/types';

interface AiReasoningLogProps {
  steps: PipelineStep[];
}

export function AiReasoningLog({ steps }: AiReasoningLogProps) {
  const [isExpanded, setIsExpanded] = useState(true);

  const completedSteps = steps.filter(s => s.status === 'completed' || s.status === 'active');
  if (completedSteps.length === 0) return null;

  return (
    <ExpandableSection
      toggleText="Pipeline Activity"
      isExpanded={isExpanded}
      onToggle={(_e, expanded) => setIsExpanded(expanded)}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: '8px 0' }}>
        {completedSteps.map((step) => (
          <div
            key={`${step.name}-${step.startedAt ?? ''}`}
            style={{
              padding: '12px 16px',
              borderLeft: `3px solid var(--pf-t--global--color--status--${step.status === 'active' ? 'info' : 'success'}--default)`,
              background: 'var(--pf-t--global--background--color--secondary--default)',
              borderRadius: 4,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <Label
                color={step.status === 'active' ? 'blue' : 'green'}
                isCompact
              >
                {step.name}
              </Label>
              {step.startedAt && (
                <Content component="small" style={{ color: 'var(--pf-t--global--text--color--subtle)' }}>
                  {new Date(step.startedAt).toLocaleTimeString()}
                </Content>
              )}
            </div>
            <Content component="p" style={{ margin: 0 }}>
              {step.status === 'active' ? 'Running...' : 'Completed'}
            </Content>
          </div>
        ))}
      </div>
    </ExpandableSection>
  );
}

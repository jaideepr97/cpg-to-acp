import {
  ProgressStep,
  ProgressStepper,
} from '@patternfly/react-core';
import { useEffect, useState } from 'react';
import type { PipelineStep } from '../api/types';

const pulseStyle = document.createElement('style');
pulseStyle.textContent = `
@keyframes stepPulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.45; }
}
.pf-c-progress-stepper__step--pulse .pf-v6-c-progress-stepper__step-icon {
  animation: stepPulse 1.8s ease-in-out infinite;
}
`;
document.head.appendChild(pulseStyle);

function stepVariant(status: PipelineStep['status']) {
  switch (status) {
    case 'completed': return 'success' as const;
    case 'active': return 'info' as const;
    case 'failed': return 'danger' as const;
    case 'cancelled': return 'warning' as const;
    default: return 'pending' as const;
  }
}

function formatDuration(startedAt?: string, completedAt?: string): string {
  if (!startedAt) return '';
  const start = new Date(startedAt).getTime();
  const end = completedAt ? new Date(completedAt).getTime() : Date.now();
  const seconds = Math.round((end - start) / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remaining = seconds % 60;
  return `${minutes}m ${remaining}s`;
}

interface PipelineStepperProps {
  steps: PipelineStep[];
}

export function PipelineStepperComponent({ steps }: PipelineStepperProps) {
  const hasActive = steps.some(s => s.status === 'active' && s.startedAt && !s.completedAt);
  const [, tick] = useState(0);
  useEffect(() => {
    if (!hasActive) return;
    const id = setInterval(() => tick(n => n + 1), 1000);
    return () => clearInterval(id);
  }, [hasActive]);

  return (
    <ProgressStepper isVertical>
      {steps.map((step) => {
        const duration = formatDuration(step.startedAt, step.completedAt);
        return (
          <ProgressStep
            key={`${step.name}-${step.startedAt ?? ''}`}
            variant={stepVariant(step.status)}
            id={step.name}
            titleId={step.name}
            description={duration || undefined}
            isCurrent={step.status === 'active'}
            className={step.status === 'active' ? 'pf-c-progress-stepper__step--pulse' : undefined}
          >
            {step.name}{step.iteration && step.iteration > 1 ? ` (round ${step.iteration})` : ''}
          </ProgressStep>
        );
      })}
    </ProgressStepper>
  );
}

import { useQuery } from '@tanstack/react-query';
import { useCallback, useRef } from 'react';
import { api } from '../api/client';
import type { RunDetail } from '../api/types';

const FAST_INTERVAL = 2_000;
const MEDIUM_INTERVAL = 10_000;
const SLOW_INTERVAL = 30_000;
const MEDIUM_THRESHOLD = 30_000;
const SLOW_THRESHOLD = 120_000;

export function useRunDetail(runId: string) {
  const lastChangeRef = useRef<number>(Date.now());
  const lastStatusRef = useRef<string>('');

  const getInterval = useCallback((data: RunDetail | undefined, isError: boolean) => {
    if (isError || !data) return false;

    if (data.status === 'completed' || data.status === 'failed') {
      return false;
    }

    const currentStatus = `${data.status}:${data.steps.filter(s => s.status === 'completed').length}`;
    if (currentStatus !== lastStatusRef.current) {
      lastStatusRef.current = currentStatus;
      lastChangeRef.current = Date.now();
      return FAST_INTERVAL;
    }

    const elapsed = Date.now() - lastChangeRef.current;
    if (elapsed > SLOW_THRESHOLD) return SLOW_INTERVAL;
    if (elapsed > MEDIUM_THRESHOLD) return MEDIUM_INTERVAL;
    return FAST_INTERVAL;
  }, []);

  return useQuery({
    queryKey: ['run', runId],
    queryFn: () => api.getRunDetail(runId),
    refetchInterval: (query) => getInterval(query.state.data, query.state.status === 'error'),
    enabled: !!runId,
  });
}

import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';

export function useRuns() {
  return useQuery({
    queryKey: ['runs'],
    queryFn: () => api.getRuns(),
    refetchInterval: (query) => {
      if (query.state.status === 'error') return false;
      const runs = query.state.data;
      if (!runs || runs.length === 0) return false;
      const hasActive = runs.some(
        (r) => r.status !== 'completed' && r.status !== 'failed',
      );
      return hasActive ? 10_000 : false;
    },
  });
}

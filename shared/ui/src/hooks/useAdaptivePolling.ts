import { useCallback, useEffect, useRef, useState } from "react";

export interface UseAdaptivePollingOptions<T> {
  fetcher: () => Promise<T>;
  isComplete?: (data: T) => boolean;
  initialInterval?: number;
  slowInterval?: number;
  slowAfterMs?: number;
  idleInterval?: number;
  idleAfterMs?: number;
  enabled?: boolean;
}

export interface UseAdaptivePollingResult<T> {
  data: T | null;
  isLoading: boolean;
  error: Error | null;
  lastChanged: Date | null;
}

export function useAdaptivePolling<T>({
  fetcher,
  isComplete,
  initialInterval = 2000,
  slowInterval = 10000,
  slowAfterMs = 30000,
  idleInterval = 30000,
  idleAfterMs = 120000,
  enabled = true,
}: UseAdaptivePollingOptions<T>): UseAdaptivePollingResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [lastChanged, setLastChanged] = useState<Date | null>(null);

  const lastDataRef = useRef<string>("");
  const startTimeRef = useRef<number>(Date.now());
  const completedRef = useRef(false);

  const poll = useCallback(async () => {
    if (completedRef.current) return;
    try {
      setIsLoading(true);
      const result = await fetcher();
      const serialized = JSON.stringify(result);

      if (serialized !== lastDataRef.current) {
        lastDataRef.current = serialized;
        setLastChanged(new Date());
      }

      setData(result);
      setError(null);

      if (isComplete?.(result)) {
        completedRef.current = true;
      }
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setIsLoading(false);
    }
  }, [fetcher, isComplete]);

  useEffect(() => {
    if (!enabled) return;

    completedRef.current = false;
    startTimeRef.current = Date.now();
    lastDataRef.current = "";
    poll();

    const timer = setInterval(() => {
      if (completedRef.current) {
        clearInterval(timer);
        return;
      }

      const elapsed = Date.now() - startTimeRef.current;
      const currentInterval =
        elapsed > idleAfterMs
          ? idleInterval
          : elapsed > slowAfterMs
            ? slowInterval
            : initialInterval;

      const timeSinceStart = elapsed % currentInterval;
      if (timeSinceStart < initialInterval) {
        poll();
      }
    }, initialInterval);

    return () => clearInterval(timer);
  }, [enabled, poll, initialInterval, slowInterval, slowAfterMs, idleInterval, idleAfterMs]);

  return { data, isLoading, error, lastChanged };
}

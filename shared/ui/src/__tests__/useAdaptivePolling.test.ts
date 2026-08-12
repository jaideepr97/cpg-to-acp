import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useAdaptivePolling } from "../hooks/useAdaptivePolling";

describe("useAdaptivePolling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns null data and no error initially", () => {
    const fetcher = vi.fn().mockResolvedValue({ status: "ok" });
    const { result } = renderHook(() =>
      useAdaptivePolling({ fetcher, enabled: false }),
    );

    expect(result.current.data).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it("fetches data immediately when enabled", async () => {
    const fetcher = vi.fn().mockResolvedValue({ count: 1 });
    const { result } = renderHook(() => useAdaptivePolling({ fetcher }));

    await act(() => vi.advanceTimersByTimeAsync(0));

    expect(result.current.data).toEqual({ count: 1 });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("does not fetch when disabled", async () => {
    const fetcher = vi.fn().mockResolvedValue({ count: 1 });
    renderHook(() => useAdaptivePolling({ fetcher, enabled: false }));

    await act(() => vi.advanceTimersByTimeAsync(5000));
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("polls at the initial interval", async () => {
    const fetcher = vi.fn().mockResolvedValue({ count: 1 });
    renderHook(() =>
      useAdaptivePolling({ fetcher, initialInterval: 1000 }),
    );

    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(fetcher).toHaveBeenCalledTimes(1);

    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(fetcher).toHaveBeenCalledTimes(2);

    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(fetcher).toHaveBeenCalledTimes(3);
  });

  it("stops polling when isComplete returns true", async () => {
    vi.useRealTimers();

    const fetcher = vi
      .fn()
      .mockResolvedValueOnce({ done: false })
      .mockResolvedValueOnce({ done: true })
      .mockResolvedValue({ done: true });

    // Must be a stable reference — the hook includes isComplete in useCallback deps
    const isComplete = (d: { done: boolean }) => d.done;

    const { result } = renderHook(() =>
      useAdaptivePolling({
        fetcher,
        isComplete,
        initialInterval: 50,
      }),
    );

    await waitFor(() => {
      expect(result.current.data).toEqual({ done: true });
    });

    const callsAtCompletion = fetcher.mock.calls.length;

    // Wait long enough for several more polls if they were happening
    await new Promise((r) => setTimeout(r, 200));
    expect(fetcher.mock.calls.length).toBe(callsAtCompletion);

    vi.useFakeTimers();
  });

  it("sets error on fetch failure", async () => {
    const fetcher = vi.fn().mockRejectedValue(new Error("network error"));
    const { result } = renderHook(() => useAdaptivePolling({ fetcher }));

    await act(() => vi.advanceTimersByTimeAsync(0));

    expect(result.current.error).toEqual(new Error("network error"));
    expect(result.current.data).toBeNull();
  });

  it("tracks lastChanged when data changes", async () => {
    let value = 1;
    const fetcher = vi.fn().mockImplementation(() => Promise.resolve({ v: value }));

    const { result } = renderHook(() =>
      useAdaptivePolling({ fetcher, initialInterval: 1000 }),
    );

    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(result.current.lastChanged).not.toBeNull();
    const firstChange = result.current.lastChanged!.getTime();

    vi.setSystemTime(new Date(Date.now() + 1000));
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(result.current.lastChanged!.getTime()).toBe(firstChange);

    value = 2;
    vi.setSystemTime(new Date(Date.now() + 2000));
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(result.current.lastChanged!.getTime()).not.toBe(firstChange);
  });
});

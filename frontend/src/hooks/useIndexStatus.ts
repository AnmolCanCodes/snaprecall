import { useCallback, useEffect, useState } from 'react';
import {
  describeError,
  getIndexStatus,
  isAbortError,
  pauseIndexing,
  resumeIndexing,
  startScan,
} from '../api/client';
import type { IndexStatus, ScanResult } from '../api/types';

export const BUSY_INTERVAL_MS = 2000;
export const IDLE_INTERVAL_MS = 15000;

export type PendingAction = 'scan' | 'pause' | 'resume';

export interface IndexStatusState {
  status: IndexStatus | null;
  error: string | null;
  pendingAction: PendingAction | null;
  actionError: string | null;
  scanResult: ScanResult | null;
  pause: () => void;
  resume: () => void;
  scan: () => void;
}

/** Work is in progress when something is processing, or pending and not paused. */
function isBusy(status: IndexStatus): boolean {
  return status.processing > 0 || (status.pending > 0 && !status.paused);
}

/**
 * Poll the indexing status: fast while busy, slow when idle, and not at all while the tab
 * is hidden. Also exposes the pause, resume and scan actions.
 */
export function useIndexStatus(): IndexStatusState {
  const [status, setStatus] = useState<IndexStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [scanResult, setScanResult] = useState<ScanResult | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const inflight: { current: AbortController | null } = { current: null };

    const schedule = (delayMs: number): void => {
      timer = setTimeout(() => {
        void tick();
      }, delayMs);
    };

    async function tick(): Promise<void> {
      if (document.hidden) {
        return;
      }
      const request = new AbortController();
      inflight.current = request;
      try {
        const next = await getIndexStatus(request.signal);
        if (cancelled || request.signal.aborted) {
          return;
        }
        setStatus(next);
        setError(null);
        schedule(isBusy(next) ? BUSY_INTERVAL_MS : IDLE_INTERVAL_MS);
      } catch (failure) {
        if (cancelled || request.signal.aborted || isAbortError(failure)) {
          return;
        }
        setError(describeError(failure));
        schedule(IDLE_INTERVAL_MS);
      }
    }

    const onVisibilityChange = (): void => {
      clearTimeout(timer);
      inflight.current?.abort();
      if (!document.hidden) {
        void tick();
      }
    };

    document.addEventListener('visibilitychange', onVisibilityChange);
    void tick();

    return () => {
      cancelled = true;
      clearTimeout(timer);
      inflight.current?.abort();
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, [reloadKey]);

  const run = useCallback(async (action: PendingAction): Promise<void> => {
    setPendingAction(action);
    setActionError(null);
    try {
      if (action === 'scan') {
        setScanResult(await startScan());
      } else {
        setStatus(await (action === 'pause' ? pauseIndexing() : resumeIndexing()));
      }
      setReloadKey((value) => value + 1);
    } catch (failure) {
      setActionError(describeError(failure));
    } finally {
      setPendingAction(null);
    }
  }, []);

  const pause = useCallback(() => void run('pause'), [run]);
  const resume = useCallback(() => void run('resume'), [run]);
  const scan = useCallback(() => void run('scan'), [run]);

  return { status, error, pendingAction, actionError, scanResult, pause, resume, scan };
}
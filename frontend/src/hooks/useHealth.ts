import { useCallback, useEffect, useState } from 'react';
import { describeError, getHealth, isAbortError } from '../api/client';
import type { HealthResponse } from '../api/types';

export interface HealthState {
  health: HealthResponse | null;
  error: string | null;
  loaded: boolean;
  reload: () => void;
}

/** Load /api/health on mount and again whenever the window regains focus. */
export function useHealth(): HealthState {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    getHealth(controller.signal).then(
      (next) => {
        if (controller.signal.aborted) {
          return;
        }
        setHealth(next);
        setError(null);
        setLoaded(true);
      },
      (failure: unknown) => {
        if (controller.signal.aborted || isAbortError(failure)) {
          return;
        }
        setError(describeError(failure));
        setLoaded(true);
      },
    );
    return () => controller.abort();
  }, [reloadKey]);

  const reload = useCallback(() => setReloadKey((value) => value + 1), []);

  useEffect(() => {
    window.addEventListener('focus', reload);
    return () => window.removeEventListener('focus', reload);
  }, [reload]);

  return { health, error, loaded, reload };
}
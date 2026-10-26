import { useCallback, useEffect, useRef, useState } from 'react';
import { describeError, isAbortError, search } from '../api/client';
import type { SearchResponse } from '../api/types';

export const DEFAULT_RESULT_LIMIT = 48;

export interface SearchState {
  /** Last successful response. Kept while a newer query loads so the grid can be dimmed. */
  response: SearchResponse | null;
  loading: boolean;
  error: string | null;
  retry: () => void;
  /** Refetch the same query without showing a loading state. */
  refresh: () => void;
}

/** Run a search whenever the query changes, cancelling any request that became stale. */
export function useSearch(query: string, limit: number = DEFAULT_RESULT_LIMIT): SearchState {
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const quietRef = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    const quiet = quietRef.current;
    quietRef.current = false;
    if (!quiet) {
      setLoading(true);
      setError(null);
    }

    search(query, limit, controller.signal).then(
      (next) => {
        if (controller.signal.aborted) {
          return;
        }
        setResponse(next);
        setError(null);
        setLoading(false);
      },
      (failure: unknown) => {
        if (controller.signal.aborted || isAbortError(failure)) {
          return;
        }
        if (!quiet) {
          setError(describeError(failure));
        }
        setLoading(false);
      },
    );

    return () => controller.abort();
  }, [query, limit, attempt]);

  const retry = useCallback(() => setAttempt((value) => value + 1), []);
  const refresh = useCallback(() => {
    quietRef.current = true;
    setAttempt((value) => value + 1);
  }, []);

  return { response, loading, error, retry, refresh };
}
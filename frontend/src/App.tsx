import { useCallback, useEffect, useRef, useState } from 'react';
import { HealthBanner } from './components/HealthBanner';
import { ImageModal } from './components/ImageModal';
import { IndexStatusBar } from './components/IndexStatus';
import { ResultGrid } from './components/ResultGrid';
import { SearchBar } from './components/SearchBar';
import { configResult } from './config';
import { useDebouncedValue } from './hooks/useDebouncedValue';
import { useHealth } from './hooks/useHealth';
import type { HealthState } from './hooks/useHealth';
import { useIndexStatus } from './hooks/useIndexStatus';
import { useSearch } from './hooks/useSearch';

const QUERY_PARAM = 'q';
const DEBOUNCE_MS = 300;

function readInitialQuery(): string {
  return new URLSearchParams(window.location.search).get(QUERY_PARAM) ?? '';
}

function writeQuery(query: string): void {
  const url = new URL(window.location.href);
  if (query.trim() === '') {
    url.searchParams.delete(QUERY_PARAM);
  } else {
    url.searchParams.set(QUERY_PARAM, query);
  }
  window.history.replaceState(null, '', url);
}

/** The privacy statement must match the active provider, so it waits for the health report. */
function privacyLine({ health }: HealthState): string | null {
  if (health === null) {
    return null;
  }
  if (health.provider_name === 'gemini') {
    return 'Hosted mode: screenshots and search text are sent to Google Gemini. Set LLM_PROVIDER=ollama to keep everything on your machine.';
  }
  return 'Everything runs on your machine. Your screenshots never leave it.';
}

function Workspace() {
  const [query, setQuery] = useState(readInitialQuery);
  const debounced = useDebouncedValue(query, DEBOUNCE_MS);
  const trimmed = debounced.trim();
  const search = useSearch(trimmed);
  const indexState = useIndexStatus();
  const healthState = useHealth();
  const [openId, setOpenId] = useState<number | null>(null);
  const openerRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    writeQuery(query);
  }, [query]);

  const hits = search.response?.results ?? [];
  const openIndex = openId === null ? -1 : hits.findIndex((hit) => hit.image.id === openId);

  useEffect(() => {
    if (openId !== null && openIndex === -1) {
      setOpenId(null);
    }
  }, [openId, openIndex]);

  const recentView =
    trimmed === '' && search.response !== null && search.response.query.trim() === '';
  const doneCount = indexState.status?.done;
  const previousDone = useRef<number | undefined>(undefined);
  const { refresh } = search;

  useEffect(() => {
    if (doneCount === undefined) {
      return;
    }
    if (previousDone.current !== undefined && doneCount > previousDone.current && recentView) {
      refresh();
    }
    previousDone.current = doneCount;
  }, [doneCount, recentView, refresh]);

  const handleOpen = useCallback((id: number, opener: HTMLElement) => {
    openerRef.current = opener;
    setOpenId(id);
  }, []);
  const handleClose = useCallback(() => setOpenId(null), []);
  const handleIndexChange = useCallback(
    (index: number) => {
      const hit = hits[index];
      if (hit) {
        setOpenId(hit.image.id);
      }
    },
    [hits],
  );

  const footer = privacyLine(healthState);

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <h1>SnapRecall</h1>
          <p>Find any screenshot by typing what you remember.</p>
        </div>
        <IndexStatusBar state={indexState} />
      </header>

      <main className="app-main">
        <SearchBar value={query} onChange={setQuery} shortcutsEnabled={openIndex === -1} />
        <HealthBanner state={healthState} />
        <ResultGrid
          response={search.response}
          loading={search.loading}
          error={search.error}
          onRetry={search.retry}
          onOpen={handleOpen}
        />
      </main>

      <footer className="app-footer">{footer !== null ? <p>{footer}</p> : null}</footer>

      {openIndex !== -1 ? (
        <ImageModal
          hits={hits}
          index={openIndex}
          opener={openerRef.current}
          onIndexChange={handleIndexChange}
          onClose={handleClose}
        />
      ) : null}
    </div>
  );
}

export default function App() {
  if (!configResult.ok) {
    return (
      <main className="config-error" role="alert">
        <h1>SnapRecall is not configured</h1>
        <p>{configResult.message}</p>
      </main>
    );
  }
  return <Workspace />;
}
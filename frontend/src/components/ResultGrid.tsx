import { useId } from 'react';
import type { SearchResponse } from '../api/types';
import { formatNumber } from '../utils/format';
import { EmptyState } from './EmptyState';
import { InfoIcon } from './icons';
import { ImageCard } from './ImageCard';
import { SkeletonGrid } from './Skeleton';

interface Props {
  response: SearchResponse | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  onOpen: (id: number, opener: HTMLElement) => void;
}

function describeCount(response: SearchResponse | null, loading: boolean): string {
  if (response === null) {
    return loading ? 'Searching...' : '';
  }
  const count = response.results.length;
  const query = response.query.trim();
  const plural = count === 1 ? '' : 's';
  if (query === '') {
    return count === 0
      ? 'No screenshots indexed yet'
      : `Showing ${formatNumber(count)} recent screenshot${plural}`;
  }
  return count === 0
    ? `No results for “${query}”`
    : `${formatNumber(count)} result${plural} for “${query}”`;
}

export function ResultGrid({ response, loading, error, onRetry, onOpen }: Props) {
  const headingId = useId();
  const isRecent = response !== null && response.query.trim() === '';

  let body;
  if (error !== null) {
    body = <EmptyState variant="error" message={error} onRetry={onRetry} />;
  } else if (response === null) {
    body = <SkeletonGrid />;
  } else if (response.results.length === 0) {
    body = isRecent ? (
      <EmptyState variant="empty-library" />
    ) : (
      <EmptyState variant="no-results" query={response.query.trim()} />
    );
  } else {
    body = (
      <ul className={loading ? 'grid grid--dimmed' : 'grid'}>
        {response.results.map((hit) => (
          <ImageCard key={hit.image.id} hit={hit} onOpen={onOpen} />
        ))}
      </ul>
    );
  }

  return (
    <section className="results" aria-labelledby={headingId} aria-busy={loading}>
      <div className="results__header">
        <h2 id={headingId}>{isRecent ? 'Recent screenshots' : 'Results'}</h2>
        <p className="results__count" role="status" aria-live="polite">
          {error === null ? describeCount(response, loading) : ''}
        </p>
      </div>
      {response?.degraded ? (
        <p className="notice">
          <InfoIcon size={16} />
          <span>Smart search is offline, showing keyword matches only.</span>
        </p>
      ) : null}
      {body}
    </section>
  );
}
import { AlertIcon, ImageOffIcon, RefreshIcon } from './icons';

type Props =
  | { variant: 'no-results'; query: string }
  | { variant: 'empty-library' }
  | { variant: 'error'; message: string; onRetry: () => void };

export function EmptyState(props: Props) {
  if (props.variant === 'error') {
    return (
      <div className="empty" role="alert">
        <AlertIcon size={28} />
        <h3>Search did not work</h3>
        <p className="muted">{props.message}</p>
        <button type="button" className="btn btn--primary" onClick={props.onRetry}>
          <RefreshIcon size={16} />
          <span>Retry</span>
        </button>
      </div>
    );
  }

  if (props.variant === 'empty-library') {
    return (
      <div className="empty">
        <ImageOffIcon size={28} />
        <h3>Nothing indexed yet</h3>
        <ul>
          <li>Check that SCREENSHOT_DIR in .env points to your screenshots folder.</li>
          <li>Press “Scan folder now” above to look for screenshots.</li>
          <li>Indexing is slow and steady, so the first results can take a little while.</li>
        </ul>
      </div>
    );
  }

  return (
    <div className="empty">
      <ImageOffIcon size={28} />
      <h3>No screenshots match “{props.query}”</h3>
      <ul>
        <li>Try fewer words.</li>
        <li>Try the same idea in Hindi or English.</li>
        <li>Check that indexing is finished. New screenshots appear once they are indexed.</li>
      </ul>
    </div>
  );
}
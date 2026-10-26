import type { IndexStatus, PausedReason } from '../api/types';
import type { IndexStatusState } from '../hooks/useIndexStatus';
import { formatNumber } from '../utils/format';
import { PauseIcon, PlayIcon, RefreshIcon } from './icons';

interface Props {
  state: IndexStatusState;
}

type Mode = 'paused' | 'waiting' | 'working' | 'idle';

const PAUSE_REASON_TEXT: Record<PausedReason, string> = {
  quota_exhausted:
    'Paused: the model provider’s daily quota is used up. It resumes after midnight, or press Resume.',
  daily_budget:
    'Paused: today’s request budget is reached. It resumes after midnight, or press Resume.',
};

function getMode(status: IndexStatus): Mode {
  if (status.paused) {
    return 'paused';
  }
  const hasWork = status.pending > 0 || status.processing > 0;
  if (hasWork && !status.provider_ok) {
    return 'waiting';
  }
  return hasWork ? 'working' : 'idle';
}

const ANNOUNCEMENTS: Record<Mode, string> = {
  paused: 'Indexing paused.',
  waiting: 'Indexing is waiting for the model provider.',
  working: 'Indexing in progress.',
  idle: 'Indexing is up to date.',
};

function describe(status: IndexStatus, mode: Mode): string {
  switch (mode) {
    case 'paused':
      return status.paused_reason !== null
        ? PAUSE_REASON_TEXT[status.paused_reason]
        : 'Paused by you. Press Resume to continue.';
    case 'waiting':
      return 'Waiting for the model provider. SnapRecall will retry automatically.';
    case 'working':
      return status.current_filename !== null
        ? `Reading ${status.current_filename}`
        : 'Working through your screenshots';
    case 'idle':
      return status.total === 0 ? 'No screenshots found yet.' : 'All caught up.';
  }
}

export function IndexStatusBar({ state }: Props) {
  const { status, error, pendingAction, actionError, scanResult, pause, resume, scan } = state;
  const busy = pendingAction !== null;

  if (status === null) {
    return (
      <section className="status-bar" aria-label="Indexing status">
        <p className="status-bar__detail">
          {error !== null ? 'Indexing status is unavailable.' : 'Checking indexing status...'}
        </p>
      </section>
    );
  }

  const mode = getMode(status);
  const percent = status.total > 0 ? Math.round((status.done / status.total) * 100) : 0;

  return (
    <section className="status-bar" aria-label="Indexing status">
      <p className="sr-only" role="status">
        {ANNOUNCEMENTS[mode]}
      </p>
      <div className="status-bar__top">
        <span className="status-bar__count">
          {formatNumber(status.done)} of {formatNumber(status.total)} indexed
        </span>
        <span className="muted">
          {status.total > 0 ? `${percent}%` : ''}
          {status.failed > 0 ? ` · ${formatNumber(status.failed)} could not be read` : ''}
        </span>
      </div>
      <progress
        className="progress"
        max={Math.max(status.total, 1)}
        value={status.done}
        aria-label="Indexing progress"
      />
      <p className={mode === 'paused' && status.paused_reason !== null ? 'status-bar__note status-bar__note--warn' : 'status-bar__detail'}>
        {describe(status, mode)}
      </p>
      {mode === 'working' ? (
        <p className="status-bar__note">
          Slow and steady: one screenshot at a time, so your computer stays usable.
        </p>
      ) : null}
      {status.requests_today > 0 ? (
        <p className="status-bar__note">
          {formatNumber(status.requests_today)} model request
          {status.requests_today === 1 ? '' : 's'} today
        </p>
      ) : null}
      {scanResult !== null ? (
        <p className="status-bar__note" role="status">
          Scan finished: {scanResult.added} new, {scanResult.requeued} changed,{' '}
          {scanResult.removed} removed.
        </p>
      ) : null}
      <div className="status-bar__actions">
        {status.paused ? (
          <button type="button" className="btn btn--small btn--primary" disabled={busy} onClick={resume}>
            <PlayIcon size={16} />
            <span>{pendingAction === 'resume' ? 'Resuming...' : 'Resume'}</span>
          </button>
        ) : (
          <button type="button" className="btn btn--small" disabled={busy} onClick={pause}>
            <PauseIcon size={16} />
            <span>{pendingAction === 'pause' ? 'Pausing...' : 'Pause'}</span>
          </button>
        )}
        <button type="button" className="btn btn--small" disabled={busy} onClick={scan}>
          <RefreshIcon size={16} />
          <span>{pendingAction === 'scan' ? 'Scanning...' : 'Scan folder now'}</span>
        </button>
      </div>
      {actionError !== null ? (
        <p className="status-bar__error" role="alert">
          {actionError}
        </p>
      ) : null}
    </section>
  );
}
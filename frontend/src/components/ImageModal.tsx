import { useEffect, useId, useRef, useState } from 'react';
import { fetchFileBlob, fileUrl, getImage, isAbortError, describeError } from '../api/client';
import type { ImageBase, ImageDetail, SearchHit } from '../api/types';
import {
  formatBytes,
  formatDateTime,
  formatDimensions,
} from '../utils/format';
import { CopyButton } from './CopyButton';
import {
  ChevronLeftIcon,
  ChevronRightIcon,
  CloseIcon,
  DownloadIcon,
  ExternalLinkIcon,
} from './icons';
import { Skeleton } from './Skeleton';

interface Props {
  hits: SearchHit[];
  index: number;
  /** The element that opened the modal. Focus returns to it on close. */
  opener: HTMLElement | null;
  onIndexChange: (index: number) => void;
  onClose: () => void;
}

const FOCUSABLE = 'a[href], button:not([disabled]), summary, [tabindex]:not([tabindex="-1"])';
const FIELD_TAGS = new Set(['INPUT', 'TEXTAREA', 'SELECT']);
const REVOKE_DELAY_MS = 1000;

type PreviewState = 'loading' | 'ready' | 'error';

function ModalBody({ image, titleId }: { image: ImageBase; titleId: string }) {
  const [detail, setDetail] = useState<ImageDetail | null>(null);
  const [detailFailed, setDetailFailed] = useState(false);
  const [preview, setPreview] = useState<PreviewState>('loading');
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getImage(image.id, controller.signal).then(
      (next) => {
        if (!controller.signal.aborted) {
          setDetail(next);
        }
      },
      (failure: unknown) => {
        if (!controller.signal.aborted && !isAbortError(failure)) {
          setDetailFailed(true);
        }
      },
    );
    return () => controller.abort();
  }, [image.id]);

  async function download(): Promise<void> {
    setDownloading(true);
    setDownloadError(null);
    try {
      const blob = await fetchFileBlob(image.id);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = image.filename;
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), REVOKE_DELAY_MS);
    } catch (failure) {
      setDownloadError(describeError(failure));
    } finally {
      setDownloading(false);
    }
  }

  const visibleText = image.visible_text.trim();
  const ocrText = detail?.ocr_text.trim() ?? '';
  const dimensions = formatDimensions(image.width, image.height);
  const size = formatBytes(image.size_bytes);
  const indexed = formatDateTime(image.indexed_at);

  return (
    <div className="modal__content">
      <div className="modal__preview">
        {preview === 'loading' ? <Skeleton /> : null}
        {preview === 'error' ? (
          <p className="error-text">The original file is not available.</p>
        ) : (
          <img
            src={fileUrl(image.id)}
            alt={image.summary || image.filename}
            hidden={preview === 'loading'}
            onLoad={() => setPreview('ready')}
            onError={() => setPreview('error')}
          />
        )}
      </div>

      <div className="modal__info">
        <div>
          <h2 id={titleId} className="modal__title">
            {image.filename}
          </h2>
          {image.summary !== '' ? <p>{image.summary}</p> : null}
        </div>

        {image.tags.length > 0 ? (
          <ul className="tags" aria-label="Tags">
            {image.tags.map((tag) => (
              <li key={tag} className="tag">
                {tag}
              </li>
            ))}
          </ul>
        ) : null}

        <dl className="modal__meta">
          {image.app_type !== '' ? (
            <>
              <dt>Type</dt>
              <dd>{image.app_type}</dd>
            </>
          ) : null}
          {dimensions !== null ? (
            <>
              <dt>Size</dt>
              <dd>{dimensions}</dd>
            </>
          ) : null}
          {size !== null ? (
            <>
              <dt>File</dt>
              <dd>{size}</dd>
            </>
          ) : null}
          {indexed !== '' ? (
            <>
              <dt>Indexed</dt>
              <dd>{indexed}</dd>
            </>
          ) : null}
        </dl>

        <div className="modal__actions">
          <CopyButton text={image.filename} label="Copy filename" />
          <a
            className="btn btn--small"
            href={fileUrl(image.id)}
            target="_blank"
            rel="noopener noreferrer"
          >
            <ExternalLinkIcon size={16} />
            <span>Open original</span>
          </a>
          <button
            type="button"
            className="btn btn--small"
            disabled={downloading}
            onClick={() => void download()}
          >
            <DownloadIcon size={16} />
            <span>{downloading ? 'Downloading...' : 'Download'}</span>
          </button>
        </div>
        {downloadError !== null ? (
          <p className="error-text" role="alert">
            {downloadError}
          </p>
        ) : null}

        <details className="modal__text">
          <summary>Text found in this screenshot</summary>
          {visibleText !== '' ? (
            <>
              <h3>Read by the model</h3>
              <pre>{visibleText}</pre>
            </>
          ) : null}
          {ocrText !== '' ? (
            <>
              <h3>OCR text</h3>
              <pre>{ocrText}</pre>
            </>
          ) : null}
          {visibleText === '' && ocrText === '' ? (
            <p className="muted">
              {detail !== null
                ? 'No text was found.'
                : detailFailed
                  ? 'Could not load the full text.'
                  : 'Loading text...'}
            </p>
          ) : null}
        </details>
      </div>
    </div>
  );
}

export function ImageModal({ hits, index, opener, onIndexChange, onClose }: Props) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const total = hits.length;
  const hit = hits[index];

  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    document.body.classList.add('modal-open');
    closeRef.current?.focus();
    return () => {
      document.body.classList.remove('modal-open');
      const target = opener?.isConnected ? opener : previous;
      if (target?.isConnected) {
        target.focus();
      }
    };
  }, [opener]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
        return;
      }
      const inField = event.target instanceof HTMLElement && FIELD_TAGS.has(event.target.tagName);
      if (!inField && event.key === 'ArrowLeft' && index > 0) {
        event.preventDefault();
        onIndexChange(index - 1);
        return;
      }
      if (!inField && event.key === 'ArrowRight' && index < total - 1) {
        event.preventDefault();
        onIndexChange(index + 1);
        return;
      }
      if (event.key === 'Tab') {
        const dialog = dialogRef.current;
        if (!dialog) {
          return;
        }
        const items = Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE));
        const first = items[0];
        const last = items[items.length - 1];
        if (!first || !last) {
          event.preventDefault();
          return;
        }
        const active = document.activeElement;
        const outside = !dialog.contains(active);
        if (event.shiftKey && (active === first || outside)) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && (active === last || outside)) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [index, total, onClose, onIndexChange]);

  if (!hit) {
    return null;
  }

  return (
    <div
      className="modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <div
        ref={dialogRef}
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <div className="modal__bar">
          <div className="modal__nav">
            <button
              type="button"
              className="btn btn--icon"
              aria-label="Previous screenshot"
              disabled={index === 0}
              onClick={() => onIndexChange(index - 1)}
            >
              <ChevronLeftIcon />
            </button>
            <span aria-live="polite">
              {index + 1} of {total}
            </span>
            <button
              type="button"
              className="btn btn--icon"
              aria-label="Next screenshot"
              disabled={index >= total - 1}
              onClick={() => onIndexChange(index + 1)}
            >
              <ChevronRightIcon />
            </button>
          </div>
          <button
            ref={closeRef}
            type="button"
            className="btn btn--icon"
            aria-label="Close preview"
            onClick={onClose}
          >
            <CloseIcon />
          </button>
        </div>
        <ModalBody key={hit.image.id} image={hit.image} titleId={titleId} />
      </div>
    </div>
  );
}
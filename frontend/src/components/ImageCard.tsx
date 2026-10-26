import { useState } from 'react';
import { thumbnailUrl } from '../api/client';
import type { SearchHit } from '../api/types';
import { formatRelativeTime, parseSnippet } from '../utils/format';
import { ImageOffIcon } from './icons';

interface Props {
  hit: SearchHit;
  onOpen: (id: number, opener: HTMLElement) => void;
}

const MAX_CARD_TAGS = 3;

function Snippet({ text }: { text: string }) {
  return (
    <>
      {parseSnippet(text).map((part, index) =>
        part.match ? <mark key={index}>{part.text}</mark> : <span key={index}>{part.text}</span>,
      )}
    </>
  );
}

export function ImageCard({ hit, onOpen }: Props) {
  const { image, snippet } = hit;
  const [thumbnailFailed, setThumbnailFailed] = useState(false);
  const label = image.summary || image.filename;
  const when = image.indexed_at ?? image.created_at;

  return (
    <li>
      <button
        type="button"
        className="card"
        aria-label={`Open screenshot: ${label}`}
        onClick={(event) => onOpen(image.id, event.currentTarget)}
      >
        <span className="card__frame">
          {thumbnailFailed ? (
            <span className="card__fallback">
              <ImageOffIcon size={28} />
            </span>
          ) : (
            <img
              src={thumbnailUrl(image.id)}
              alt={label}
              loading="lazy"
              decoding="async"
              onError={() => setThumbnailFailed(true)}
            />
          )}
        </span>
        <span className="card__body">
          <span className="card__row">
            {image.app_type !== '' ? <span className="badge">{image.app_type}</span> : <span />}
            <time dateTime={when}>{formatRelativeTime(when)}</time>
          </span>
          <span className="card__summary" title={label}>
            {label}
          </span>
          {snippet ? (
            <span className="card__snippet">
              <Snippet text={snippet} />
            </span>
          ) : null}
          {image.tags.length > 0 ? (
            <span className="tags">
              {image.tags.slice(0, MAX_CARD_TAGS).map((tag) => (
                <span key={tag} className="tag">
                  {tag}
                </span>
              ))}
            </span>
          ) : null}
        </span>
      </button>
    </li>
  );
}
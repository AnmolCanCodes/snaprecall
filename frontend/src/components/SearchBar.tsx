import { useEffect, useId, useRef } from 'react';
import { CloseIcon, SearchIcon } from './icons';

interface Props {
  value: string;
  onChange: (value: string) => void;
  shortcutsEnabled?: boolean;
}

const TYPING_TAGS = new Set(['INPUT', 'TEXTAREA', 'SELECT']);

function isTypingTarget(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement && (target.isContentEditable || TYPING_TAGS.has(target.tagName))
  );
}

export function SearchBar({ value, onChange, shortcutsEnabled = true }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const inputId = useId();

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!shortcutsEnabled) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key !== '/' || event.ctrlKey || event.metaKey || event.altKey) {
        return;
      }
      if (isTypingTarget(event.target)) {
        return;
      }
      event.preventDefault();
      inputRef.current?.focus();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [shortcutsEnabled]);

  return (
    <form role="search" className="search" onSubmit={(event) => event.preventDefault()}>
      <label htmlFor={inputId} className="sr-only">
        Search screenshots
      </label>
      <span className="search__icon">
        <SearchIcon size={22} />
      </span>
      <input
        ref={inputRef}
        id={inputId}
        className="search__input"
        type="text"
        inputMode="search"
        enterKeyHint="search"
        autoComplete="off"
        autoCorrect="off"
        spellCheck={false}
        aria-keyshortcuts="/"
        placeholder="Try “rahul payment 2500” or “docker permission error”"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Escape' && value !== '') {
            event.preventDefault();
            onChange('');
          }
        }}
      />
      {value !== '' ? (
        <button
          type="button"
          className="search__clear"
          aria-label="Clear search"
          onClick={() => {
            onChange('');
            inputRef.current?.focus();
          }}
        >
          <CloseIcon size={18} />
        </button>
      ) : (
        <kbd className="search__hint" aria-hidden="true">
          /
        </kbd>
      )}
    </form>
  );
}
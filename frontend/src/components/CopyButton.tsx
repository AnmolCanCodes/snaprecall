import { useEffect, useRef, useState } from 'react';
import { copyText } from '../utils/format';
import { CheckIcon, CopyIcon } from './icons';

interface Props {
  text: string;
  label: string;
}

type CopyState = 'idle' | 'copied' | 'failed';

const RESET_DELAY_MS = 2000;

export function CopyButton({ text, label }: Props) {
  const [state, setState] = useState<CopyState>('idle');
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => () => clearTimeout(timer.current), []);

  async function handleClick(): Promise<void> {
    const copied = await copyText(text);
    setState(copied ? 'copied' : 'failed');
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setState('idle'), RESET_DELAY_MS);
  }

  const visibleLabel = state === 'copied' ? 'Copied' : state === 'failed' ? 'Copy failed' : label;

  return (
    <>
      <button type="button" className="btn btn--small" onClick={() => void handleClick()}>
        {state === 'copied' ? <CheckIcon size={16} /> : <CopyIcon size={16} />}
        <span>{visibleLabel}</span>
      </button>
      <span className="sr-only" role="status">
        {state === 'copied' ? 'Copied to clipboard' : ''}
      </span>
    </>
  );
}
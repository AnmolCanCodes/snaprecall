import { useState } from 'react';
import type { HealthState } from '../hooks/useHealth';
import { CopyButton } from './CopyButton';
import { AlertIcon, CloseIcon } from './icons';

interface Props {
  state: HealthState;
}

export interface Problem {
  id: string;
  severity: 'error' | 'warning';
  title: string;
  body: string;
  command?: string;
}

const PULL_COMMAND = /ollama pull \S+/;
const START_BACKEND = 'uvicorn app.main:app --port 8000';

function modelProblem(id: string, label: string, detail: string | null): Problem {
  const command = detail?.match(PULL_COMMAND)?.[0];
  if (command !== undefined) {
    return {
      id,
      severity: 'warning',
      title: `The ${label} model is not downloaded`,
      body: 'Download it once, then reload this page:',
      command,
    };
  }
  return {
    id,
    severity: 'warning',
    title: `The ${label} model is not available`,
    body: detail ?? 'Check VISION_MODEL and EMBEDDING_MODEL in .env.',
  };
}

/** Turn a health report into the list of problems the user can act on. */
export function deriveProblems({ health, error, loaded }: HealthState): Problem[] {
  if (error !== null) {
    return [
      {
        id: 'backend',
        severity: 'error',
        title: 'Cannot reach the backend',
        body: `${error} Run this inside the backend folder, with its virtual environment active:`,
        command: START_BACKEND,
      },
    ];
  }
  if (!loaded || health === null) {
    return [];
  }

  const problems: Problem[] = [];
  const providerName = health.provider_name;
  const providerReachable = health.provider?.ok ?? true;

  if (health.embedding_mismatch === true) {
    problems.push({
      id: 'embedding-mismatch',
      severity: 'error',
      title: 'The embedding model changed',
      body: 'Indexing is stopped so vectors from different models are never mixed. Stop the backend, delete the data folder (data/snaprecall.db), and start it again to rebuild the index.',
    });
  }
  if (providerName === 'gemini' && health.api_key_configured === false) {
    problems.push({
      id: 'api-key',
      severity: 'error',
      title: 'Gemini API key is missing',
      body: 'Add GEMINI_API_KEY to the .env file in the project root, then restart the backend.',
    });
  } else if (health.provider !== undefined && !providerReachable) {
    if (providerName === 'gemini') {
      problems.push({
        id: 'provider',
        severity: 'error',
        title: 'Cannot reach Gemini',
        body: health.provider.detail ?? 'Check your internet connection and API key.',
      });
    } else {
      problems.push({
        id: 'provider',
        severity: 'error',
        title: 'Ollama is not running',
        body: 'Start Ollama, then reload this page:',
        command: 'ollama serve',
      });
    }
  }
  if (providerReachable) {
    if (!health.vision_model.ok) {
      problems.push(modelProblem('vision-model', 'vision', health.vision_model.detail));
    }
    if (!health.embedding_model.ok) {
      problems.push(modelProblem('embedding-model', 'embedding', health.embedding_model.detail));
    }
  }
  if (!health.tesseract.ok) {
    problems.push({
      id: 'tesseract',
      severity: 'warning',
      title: 'Text recognition (OCR) is not ready',
      body: `${health.tesseract.detail ?? 'Tesseract was not found.'} Search still works, but exact text matches will be weaker.`,
    });
  }
  if (!health.screenshot_dir.ok) {
    problems.push({
      id: 'screenshot-dir',
      severity: 'error',
      title: 'Screenshot folder is not set up',
      body: `${health.screenshot_dir.detail ?? 'SCREENSHOT_DIR is not configured.'} Set SCREENSHOT_DIR in .env and restart the backend.`,
    });
  }
  if (!health.database.ok) {
    problems.push({
      id: 'database',
      severity: 'error',
      title: 'The database is not available',
      body: health.database.detail ?? 'The backend could not open its database.',
    });
  }
  return problems;
}

export function HealthBanner({ state }: Props) {
  const [dismissed, setDismissed] = useState<ReadonlySet<string>>(new Set());
  const problems = deriveProblems(state).filter((problem) => !dismissed.has(problem.id));

  if (problems.length === 0) {
    return null;
  }

  return (
    <section className="banners" aria-label="Setup problems" aria-live="polite">
      {problems.map((problem) => (
        <div
          key={problem.id}
          className={problem.severity === 'error' ? 'banner banner--error' : 'banner'}
        >
          <span className="banner__icon">
            <AlertIcon size={20} />
          </span>
          <div className="banner__content">
            <p className="banner__title">{problem.title}</p>
            <p>{problem.body}</p>
            {problem.command !== undefined ? (
              <div className="banner__command">
                <code>{problem.command}</code>
                <CopyButton text={problem.command} label="Copy command" />
              </div>
            ) : null}
          </div>
          <button
            type="button"
            className="btn btn--small btn--icon"
            aria-label={`Dismiss: ${problem.title}`}
            onClick={() => setDismissed((current) => new Set(current).add(problem.id))}
          >
            <CloseIcon size={16} />
          </button>
        </div>
      ))}
    </section>
  );
}
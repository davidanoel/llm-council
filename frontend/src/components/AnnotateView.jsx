import { useState } from 'react';
import { api } from '../api';

export default function AnnotateView({ onComplete }) {
  const [csvFile, setCsvFile] = useState(null);
  const [csvText, setCsvText] = useState('');
  const [runName, setRunName] = useState('');
  const [validation, setValidation] = useState(null);
  const [summary, setSummary] = useState(null);
  const [progressStatus, setProgressStatus] = useState(null);
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  const [running, setRunning] = useState(false);

  async function selectCsv(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    setError('');
    setStatus('Validating CSV...');
    setSummary(null);
    try {
      const text = await file.text();
      const result = await api.validateCsv(text);
      setCsvFile(file);
      setCsvText(text);
      setRunName(file.name.replace(/\.[^.]+$/, ''));
      setValidation(result);
      setStatus('CSV is ready to run.');
    } catch (err) {
      setCsvFile(null);
      setCsvText('');
      setValidation(null);
      setError(err.message);
      setStatus('');
    }
  }

  async function runCsv() {
    setError('');
    setStatus(`Annotating ${validation.valid_rows} prompts...`);
    setRunning(true);
    setSummary(null);
    setProgressStatus(null);
    try {
      const started = await api.startCsvRun(csvText, {
        runName: runName.trim() || csvFile?.name || undefined,
        sourceFilename: csvFile?.name,
      });
      setProgressStatus(started);
      setStatus('Batch annotation running...');
      const finished = await pollRunProgress(started.run_id, setProgressStatus);
      setSummary(finished.progress);
      setStatus(finished.status === 'completed' ? 'Batch annotation complete.' : 'Batch annotation finished with failures.');
      onComplete({ run: finished.run, progress: finished.progress, results: [] });
    } catch (err) {
      setError(err.message);
      setStatus('');
    } finally {
      setRunning(false);
    }
  }

  return (
    <section className="view-stack">
      {error && <div className="alert error">{error}</div>}
      {status && <div className="alert status">{status}</div>}

      <section className="panel primary-panel">
        <h2>Upload prompts</h2>
        <p className="muted">CSV requires a <code>prompt</code> column. Optional columns: <code>response</code>, <code>prompt_id</code>, <code>metadata</code>. When present, the response is classified.</p>
        <label className="file-drop">
          <span>{csvFile ? csvFile.name : 'Choose a CSV file'}</span>
          <input type="file" accept=".csv,text/csv" onChange={selectCsv} />
        </label>
        {validation && (
          <>
            <label className="run-name-field">Run name<input value={runName} onChange={(event) => setRunName(event.target.value)} /></label>
            <div className="validation-summary">
              <strong>{validation.valid_rows.toLocaleString()} valid rows</strong>
              <span>{formatTaskType(validation.task_type)}</span>
              <button type="button" disabled={running} onClick={runCsv}>{running ? 'Running...' : 'Run annotation'}</button>
            </div>
            <div className="validation-details">
              <span>Responses: <strong>{validation.rows_with_response}</strong></span>
              <span>Prompt only: <strong>{validation.rows_without_response}</strong></span>
              <span>Skipped empty prompts: <strong>{validation.skipped_empty_prompt_rows}</strong></span>
            </div>
            {validation.mixed_task_warning && <p className="warning-text">{validation.mixed_task_warning}</p>}
          </>
        )}
        {progressStatus && <LiveProgress status={progressStatus} />}
        {summary && <BatchSummary summary={summary} />}
      </section>
    </section>
  );
}

async function pollRunProgress(runId, onProgress) {
  while (true) {
    await wait(600);
    const latest = await api.runProgress(runId);
    onProgress(latest);
    if (latest.status !== 'running') return latest;
  }
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function formatTaskType(taskType) {
  return (taskType || '').replaceAll('_', ' ');
}

function BatchSummary({ summary }) {
  return (
    <div className="summary-grid">
      {['total', 'completed', 'auto_safe', 'auto_unsafe', 'human_review', 'failed', 'provider_failed'].map((key) => (
        <div key={key}><span>{key.replaceAll('_', ' ')}</span><strong>{summary[key]}</strong></div>
      ))}
      {summary.provider_failed > 0 && (
        <p className="warning-text">Some prompts need human review because model provider calls failed.</p>
      )}
    </div>
  );
}

function LiveProgress({ status }) {
  const progress = status.progress;
  const percent = progress.total ? Math.round((progress.completed + progress.failed) / progress.total * 100) : 0;
  return (
    <div className="live-progress">
      <div className="progress-header">
        <strong>{progress.completed + progress.failed} / {progress.total}</strong>
        <span>{status.status}</span>
      </div>
      <progress value={progress.completed + progress.failed} max={progress.total || 1} />
      <div className="validation-details">
        <span>Safe: <strong>{progress.auto_safe}</strong></span>
        <span>Unsafe: <strong>{progress.auto_unsafe}</strong></span>
        <span>Review: <strong>{progress.human_review}</strong></span>
        <span>Failed: <strong>{progress.failed}</strong></span>
        <span>Provider failed: <strong>{progress.provider_failed}</strong></span>
      </div>
      <p className="muted">
        {status.last_completed_prompt_id
          ? `Last completed: ${status.last_completed_prompt_id}`
          : status.current_prompt_id
            ? `Annotating: ${status.current_prompt_id}`
            : `${percent}% complete`}
      </p>
      {status.error && <p className="warning-text">{status.error}</p>}
    </div>
  );
}

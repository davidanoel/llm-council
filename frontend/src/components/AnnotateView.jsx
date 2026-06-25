import { useState } from 'react';
import { api } from '../api';

export default function AnnotateView({ onComplete }) {
  const [csvFile, setCsvFile] = useState(null);
  const [csvText, setCsvText] = useState('');
  const [runName, setRunName] = useState('');
  const [validation, setValidation] = useState(null);
  const [summary, setSummary] = useState(null);
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');

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
    try {
      const response = await api.annotateCsv(csvText, {
        runName: runName.trim() || csvFile?.name || undefined,
        sourceFilename: csvFile?.name,
      });
      setSummary(response.progress);
      setStatus('Batch annotation complete.');
      onComplete(response);
    } catch (err) {
      setError(err.message);
      setStatus('');
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
              <button type="button" onClick={runCsv}>Run annotation</button>
            </div>
            <div className="validation-details">
              <span>Responses: <strong>{validation.rows_with_response}</strong></span>
              <span>Prompt only: <strong>{validation.rows_without_response}</strong></span>
              <span>Skipped empty prompts: <strong>{validation.skipped_empty_prompt_rows}</strong></span>
            </div>
            {validation.mixed_task_warning && <p className="warning-text">{validation.mixed_task_warning}</p>}
          </>
        )}
        {summary && <BatchSummary summary={summary} />}
      </section>
    </section>
  );
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

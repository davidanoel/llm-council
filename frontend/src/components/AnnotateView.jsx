import { useState } from 'react';
import { api } from '../api';
import { DecisionSummary, VoteDetails } from './AnnotationDetails';

const JSON_SAMPLE = JSON.stringify([
  { prompt_id: 'demo-safe', prompt_text: 'How do I kill port 8080?', metadata: { source: 'demo' } },
], null, 2);

export default function AnnotateView({ onComplete }) {
  const [csvFile, setCsvFile] = useState(null);
  const [csvText, setCsvText] = useState('');
  const [validation, setValidation] = useState(null);
  const [summary, setSummary] = useState(null);
  const [singleResult, setSingleResult] = useState(null);
  const [singlePrompt, setSinglePrompt] = useState('');
  const [singleMetadata, setSingleMetadata] = useState('{}');
  const [jsonText, setJsonText] = useState(JSON_SAMPLE);
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
      const response = await api.annotateCsv(csvText);
      setSummary(response.progress);
      setStatus('Batch annotation complete.');
      onComplete(response.results);
    } catch (err) {
      setError(err.message);
      setStatus('');
    }
  }

  async function runSingle(event) {
    event.preventDefault();
    setError('');
    setStatus('Annotating prompt...');
    try {
      const metadata = singleMetadata.trim() ? JSON.parse(singleMetadata) : {};
      const result = await api.annotate({ prompt_text: singlePrompt, metadata });
      setSingleResult(result);
      setStatus('Annotation complete.');
    } catch (err) {
      setError(err.message);
      setStatus('');
    }
  }

  async function runJsonBatch() {
    setError('');
    setStatus('Running JSON batch...');
    try {
      const prompts = JSON.parse(jsonText);
      if (!Array.isArray(prompts)) throw new Error('JSON input must be an array.');
      const response = await api.annotateBatch(prompts);
      setSummary(response.progress);
      setStatus('Batch annotation complete.');
      onComplete(response.results);
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
        <p className="muted">CSV requires a <code>prompt</code> column. Optional columns: <code>prompt_id</code>, <code>metadata</code>.</p>
        <label className="file-drop">
          <span>{csvFile ? csvFile.name : 'Choose a CSV file'}</span>
          <input type="file" accept=".csv,text/csv" onChange={selectCsv} />
        </label>
        {validation && (
          <div className="validation-summary">
            <strong>{validation.valid_rows.toLocaleString()} valid rows</strong>
            <button type="button" onClick={runCsv}>Run annotation</button>
          </div>
        )}
        {summary && <BatchSummary summary={summary} />}
      </section>

      <details className="panel advanced-panel">
        <summary>Advanced: single prompt</summary>
        <form className="form advanced-content" onSubmit={runSingle}>
          <label>Prompt<textarea rows={5} required value={singlePrompt} onChange={(event) => setSinglePrompt(event.target.value)} /></label>
          <label>Metadata JSON<textarea rows={3} value={singleMetadata} onChange={(event) => setSingleMetadata(event.target.value)} /></label>
          <button type="submit">Annotate prompt</button>
        </form>
        {singleResult && (
          <div className="advanced-content">
            <DecisionSummary annotation={singleResult} />
            <details><summary>Show model votes</summary><VoteDetails annotation={singleResult} /></details>
          </div>
        )}
      </details>

      <details className="panel advanced-panel">
        <summary>Advanced: JSON batch</summary>
        <div className="advanced-content">
          <textarea rows={10} value={jsonText} onChange={(event) => setJsonText(event.target.value)} />
          <button type="button" onClick={runJsonBatch}>Run JSON batch</button>
        </div>
      </details>
    </section>
  );
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

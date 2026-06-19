import { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import { AnnotationContent, Badge, DecisionSummary, VoteDetails } from './AnnotationDetails';
import { displayLabel, effectiveLabel } from './annotationUtils';

export default function ResultsView({ refreshVersion, onReview }) {
  const [annotations, setAnnotations] = useState([]);
  const [filter, setFilter] = useState('all');
  const [selectedId, setSelectedId] = useState(null);
  const [agreement, setAgreement] = useState(null);
  const [status, setStatus] = useState('');

  const filtered = useMemo(() => annotations.filter((item) => (
    filter === 'all' || effectiveLabel(item) === filter
  )), [annotations, filter]);
  const selected = annotations.find((item) => item.prompt_id === selectedId);

  useEffect(() => {
    let active = true;
    Promise.all([api.listAnnotations(), api.agreement()])
      .then(([items, metrics]) => {
        if (active) {
          setAnnotations(items);
          setAgreement(metrics);
          setSelectedId((current) => current || items[0]?.prompt_id || null);
        }
      })
      .catch((err) => { if (active) setStatus(err.message); });
    return () => { active = false; };
  }, [refreshVersion]);

  async function downloadCsv() {
    try {
      const blob = await api.exportLabelsCsv(true);
      download(blob, 'labels.csv');
    } catch (err) {
      setStatus(err.message);
    }
  }

  async function downloadJson() {
    try {
      const labels = await api.exportLabels(true);
      download(new Blob([JSON.stringify(labels, null, 2)], { type: 'application/json' }), 'labels.json');
    } catch (err) {
      setStatus(err.message);
    }
  }

  return (
    <section className="view-stack">
      <section className="panel results-panel">
        <div className="results-toolbar">
          <div><h2>Annotation results</h2><p className="muted">{filtered.length} of {annotations.length} items</p></div>
          <div className="button-row">
            {annotations.some((item) => effectiveLabel(item) === 'needs_human_review') && <button type="button" onClick={onReview}>Review unresolved</button>}
            <button type="button" className="secondary" onClick={downloadJson}>Export JSON</button>
            <button type="button" className="secondary" onClick={downloadCsv}>Export CSV</button>
          </div>
        </div>
        {agreement && (
          <div className="metrics-grid agreement-summary">
            <div><span>Fleiss kappa</span><strong>{agreement.fleiss_kappa ?? 'N/A'}</strong></div>
            <div><span>Observed agreement</span><strong>{formatPercent(agreement.observed_agreement)}</strong></div>
            <div><span>Unanimous</span><strong>{formatPercent(agreement.unanimous_rate)}</strong></div>
            <div><span>Vote coverage</span><strong>{formatPercent(agreement.coverage_rate)}</strong></div>
          </div>
        )}
        <div className="filter-row">
          {['all', 'safe', 'unsafe', 'needs_human_review'].map((value) => (
            <button key={value} type="button" className={filter === value ? 'filter active' : 'filter'} onClick={() => setFilter(value)}>{value === 'all' ? 'All' : displayLabel(value)}</button>
          ))}
        </div>
        {status && <div className="alert error">{status}</div>}
        <div className="table-wrap">
          <table className="results-table">
            <thead><tr><th>Prompt ID</th><th>Final label</th><th>Source</th><th>Category</th><th>Status</th></tr></thead>
            <tbody>
              {filtered.map((item) => {
                const review = item.human_reviews?.at(-1);
                return (
                  <tr key={item.prompt_id} className={selectedId === item.prompt_id ? 'selected-row' : ''} onClick={() => setSelectedId(item.prompt_id)}>
                    <td>{item.prompt_id}</td>
                    <td><Badge label={effectiveLabel(item)} /></td>
                    <td>{review ? 'human' : 'AI annotators'}</td>
                    <td>{review?.unsafe_category || item.adjudication?.unsafe_category || 'none'}</td>
                    <td>{review ? 'reviewed' : item.adjudication?.decision_type}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
      {selected && (
        <section className="panel result-inspector">
          <h2>{selected.prompt_id}</h2>
          <AnnotationContent annotation={selected} />
          <DecisionSummary annotation={selected} />
          {effectiveLabel(selected) === 'needs_human_review' && <button type="button" onClick={onReview}>Set human label</button>}
          <details className="model-details"><summary>Show model votes</summary><VoteDetails annotation={selected} /></details>
        </section>
      )}
    </section>
  );
}

function download(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function formatPercent(value) {
  return value == null ? 'N/A' : `${Math.round(value * 100)}%`;
}

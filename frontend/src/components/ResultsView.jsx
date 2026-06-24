import { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import { AnnotationContent, Badge, DecisionSummary, VoteDetails } from './AnnotationDetails';
import { displayLabel, effectiveLabel } from './annotationUtils';

export default function ResultsView({ refreshVersion, onReview, onDataChanged }) {
  const [annotations, setAnnotations] = useState([]);
  const [filter, setFilter] = useState('all');
  const [searchInput, setSearchInput] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedId, setSelectedId] = useState(null);
  const [agreement, setAgreement] = useState(null);
  const [importedAnalysis, setImportedAnalysis] = useState(null);
  const [status, setStatus] = useState('');
  const [deletingId, setDeletingId] = useState(null);

  const filtered = useMemo(() => annotations.filter((item) => {
    const filterMatch = filter === 'all' || effectiveLabel(item) === filter;
    if (!filterMatch) return false;
    if (!searchQuery) return true;

    const review = item.human_reviews?.at(-1);
    const searchText = [
      item.prompt_id,
      item.prompt_text,
      item.response_text,
      item.adjudication?.unsafe_category,
      item.adjudication?.decision_type,
      review?.unsafe_category,
      effectiveLabel(item),
      displayLabel(effectiveLabel(item)),
    ].filter(Boolean).join(' ').toLowerCase();

    return searchText.includes(searchQuery);
  }), [annotations, filter, searchQuery]);
  const outcomeCounts = useMemo(() => ({
    safe: annotations.filter((item) => effectiveLabel(item) === 'safe').length,
    unsafe: annotations.filter((item) => effectiveLabel(item) === 'unsafe').length,
    humanReview: annotations.filter((item) => item.adjudication?.decision_type === 'human_review').length,
  }), [annotations]);
  const selected = annotations.find((item) => item.prompt_id === selectedId);
  const displayedAgreement = importedAnalysis?.agreement || agreement;
  const displayedTotal = importedAnalysis?.total_items ?? annotations.length;
  const displayedCounts = importedAnalysis ? {
    safe: importedAnalysis.safe_items,
    unsafe: importedAnalysis.unsafe_items,
    humanReview: importedAnalysis.human_review_items,
  } : outcomeCounts;

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

  useEffect(() => {
    const handle = setTimeout(() => {
      setSearchQuery(searchInput.trim().toLowerCase());
    }, 180);

    return () => clearTimeout(handle);
  }, [searchInput]);

  useEffect(() => {
    if (!filtered.length) {
      setSelectedId(null);
      return;
    }

    if (!filtered.some((item) => item.prompt_id === selectedId)) {
      setSelectedId(filtered[0].prompt_id);
    }
  }, [filtered, selectedId]);

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

  async function analyzeCsv(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const analysis = await api.analyzeExportCsv(await file.text());
      setImportedAnalysis({ ...analysis, fileName: file.name });
      setStatus('');
    } catch (err) {
      setStatus(err.message);
    } finally {
      event.target.value = '';
    }
  }

  async function clearDatabase() {
    const confirmed = window.confirm('Delete all stored annotations? This cannot be undone.');
    if (!confirmed) return;

    try {
      await api.clearAnnotations();
      setAnnotations([]);
      setAgreement(null);
      setImportedAnalysis(null);
      setSelectedId(null);
      setStatus('Database cleared.');
      onDataChanged();
    } catch (err) {
      setStatus(err.message);
    }
  }

  async function deletePrompt(item) {
    const confirmed = window.confirm(`Delete prompt ${item.prompt_id}? This cannot be undone.`);
    if (!confirmed) return;

    try {
      setDeletingId(item.prompt_id);
      await api.deleteAnnotation(item.prompt_id);
      const next = annotations.filter((entry) => entry.prompt_id !== item.prompt_id);
      setAnnotations(next);
      setSelectedId((current) => {
        if (current !== item.prompt_id) return current;
        return next[0]?.prompt_id || null;
      });
      setImportedAnalysis(null);
      const metrics = await api.agreement();
      setAgreement(metrics);
      setStatus(`Deleted ${item.prompt_id}.`);
      onDataChanged();
    } catch (err) {
      setStatus(err.message);
    } finally {
      setDeletingId(null);
    }
  }

  function handleResultTableKeyDown(event) {
    if (!filtered.length) return;

    const currentIndex = Math.max(0, filtered.findIndex((item) => item.prompt_id === selectedId));

    if (event.key === 'ArrowDown') {
      event.preventDefault();
      const nextIndex = Math.min(filtered.length - 1, currentIndex + 1);
      setSelectedId(filtered[nextIndex].prompt_id);
      return;
    }

    if (event.key === 'ArrowUp') {
      event.preventDefault();
      const nextIndex = Math.max(0, currentIndex - 1);
      setSelectedId(filtered[nextIndex].prompt_id);
    }
  }

  return (
    <section className="results-split">
      <section className="panel results-panel results-list-panel">
        <div className="results-toolbar">
          <div><h2>Annotation results</h2><p className="muted">{filtered.length} of {annotations.length} items</p></div>
          <div className="button-row">
            {annotations.some((item) => effectiveLabel(item) === 'needs_human_review') && <button type="button" onClick={onReview}>Review unresolved</button>}
            <button type="button" className="secondary" onClick={downloadJson}>Export JSON</button>
            <button type="button" className="secondary" onClick={downloadCsv}>Export CSV</button>
            <label className="upload-button">Analyze CSV<input type="file" accept=".csv,text/csv" onChange={analyzeCsv} /></label>
            <button type="button" className="secondary danger-button" onClick={clearDatabase}>Clear database</button>
          </div>
        </div>
        <div className="search-row">
          <label htmlFor="results-search" className="search-label">Search prompts</label>
          <input
            id="results-search"
            type="search"
            placeholder="Search by prompt id, text, response, status, or category"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
          />
        </div>
        {importedAnalysis && (
          <div className="metric-source">Metrics from <strong>{importedAnalysis.fileName}</strong><button type="button" className="filter" onClick={() => setImportedAnalysis(null)}>Use current data</button></div>
        )}
        {displayedAgreement && (
          <div className="metrics-grid agreement-summary">
            <div><span>Fleiss kappa</span><strong>{displayedAgreement.fleiss_kappa ?? 'N/A'}</strong><small>3-model chance-corrected</small></div>
            <div><span>Pairwise agreement</span><strong>{formatPercent(displayedAgreement.observed_agreement)}</strong><small>Average model-pair agreement</small></div>
            <div><span>All 3 matched</span><strong>{formatPercent(displayedAgreement.unanimous_rate)}</strong><small>Complete panels only</small></div>
            <div><span>Complete vote panels</span><strong>{formatRatio(displayedAgreement.complete_items, displayedTotal)}</strong><small>All 3 votes succeeded</small></div>
            <div><span>Final safe rate</span><strong>{formatRatio(displayedCounts.safe, displayedTotal)}</strong></div>
            <div><span>Final unsafe rate</span><strong>{formatRatio(displayedCounts.unsafe, displayedTotal)}</strong></div>
            <div><span>Human-review rate</span><strong>{formatRatio(displayedCounts.humanReview, displayedTotal)}</strong></div>
          </div>
        )}
        <div className="filter-row">
          {['all', 'safe', 'unsafe', 'needs_human_review'].map((value) => (
            <button key={value} type="button" className={filter === value ? 'filter active' : 'filter'} onClick={() => setFilter(value)}>{value === 'all' ? 'All' : displayLabel(value)}</button>
          ))}
        </div>
        {status && <div className="alert error">{status}</div>}
        <div className="table-wrap" tabIndex={0} onKeyDown={handleResultTableKeyDown}>
          <table className="results-table">
            <thead><tr><th>Prompt ID</th><th>Final label</th><th>Source</th><th>Category</th><th>Status</th><th>Updated</th><th>Actions</th></tr></thead>
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
                    <td>{item?.updated_at}</td>
                    <td className="row-actions">
                      <button
                        type="button"
                        className="secondary danger-button"
                        disabled={deletingId === item.prompt_id}
                        onClick={(event) => {
                          event.stopPropagation();
                          deletePrompt(item);
                        }}
                      >
                        {deletingId === item.prompt_id ? 'Deleting...' : 'Delete'}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
      <section className="panel result-inspector sticky-inspector">
        {selected ? (
          <>
            <h2>{selected.prompt_id}</h2>
            <AnnotationContent annotation={selected} />
            <DecisionSummary annotation={selected} />
            {effectiveLabel(selected) === 'needs_human_review' && <button type="button" onClick={onReview}>Set human label</button>}
            <details className="model-details"><summary>Show model votes</summary><VoteDetails annotation={selected} /></details>
          </>
        ) : (
          <div className="empty-view compact-empty">
            <h2>No prompt selected</h2>
            <p>Use search or filters to choose a prompt from the list.</p>
          </div>
        )}
      </section>
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

function formatRatio(count, total) {
  return total ? `${count} / ${total} (${formatPercent(count / total)})` : '0 / 0';
}

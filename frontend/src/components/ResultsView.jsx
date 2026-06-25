import { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import { AnnotationContent, Badge, DecisionSummary, VoteDetails } from './AnnotationDetails';
import HumanLabelForm from './HumanLabelForm';
import { displayLabel, effectiveLabel } from './annotationUtils';

export default function ResultsView({
  refreshVersion,
  selectedRunId,
  onRunSelected,
  onReview,
  onDataChanged,
}) {
  const [runs, setRuns] = useState([]);
  const [annotations, setAnnotations] = useState([]);
  const [filter, setFilter] = useState('all');
  const [searchInput, setSearchInput] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedId, setSelectedId] = useState(null);
  const [agreement, setAgreement] = useState(null);
  const [importedAnalysis, setImportedAnalysis] = useState(null);
  const [status, setStatus] = useState('');
  const [deletingId, setDeletingId] = useState(null);
  const [runNameDraft, setRunNameDraft] = useState('');
  const [savingRunName, setSavingRunName] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [resuming, setResuming] = useState(false);
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [overrideStatus, setOverrideStatus] = useState('');

  const selectedRun = runs.find((run) => run.run_id === selectedRunId);
  const filtered = useMemo(() => annotations.filter((item) => {
    const filterMatch = filter === 'all' || effectiveLabel(item) === filter;
    if (!filterMatch) return false;
    if (!searchQuery) return true;

    const review = item.human_reviews?.at(-1);
    const searchText = [
      item.prompt_id,
      item.prompt_text,
      item.response_text,
      item.error_message,
      item.adjudication?.unsafe_category,
      item.adjudication?.decision_type,
      item.review_reason_type,
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
    failed: annotations.filter((item) => effectiveLabel(item) === 'failed').length,
  }), [annotations]);
  const selected = annotations.find((item) => item.prompt_id === selectedId);
  const displayedAgreement = importedAnalysis?.agreement || agreement;
  const displayedTotal = importedAnalysis?.total_items ?? annotations.length;
  const displayedCounts = importedAnalysis ? {
    safe: importedAnalysis.safe_items,
    unsafe: importedAnalysis.unsafe_items,
    humanReview: importedAnalysis.human_review_items,
    failed: 0,
  } : outcomeCounts;

  useEffect(() => {
    let active = true;
    api.listRuns()
      .then((items) => {
        if (!active) return;
        setRuns(items);
        if (!selectedRunId && items[0]?.run_id) {
          onRunSelected(items[0].run_id);
        }
      })
      .catch((err) => { if (active) setStatus(err.message); });
    return () => { active = false; };
  }, [refreshVersion, selectedRunId, onRunSelected]);

  useEffect(() => {
    let active = true;
    if (!selectedRunId) {
      setAnnotations([]);
      setAgreement(null);
      setSelectedId(null);
      return () => { active = false; };
    }

    Promise.all([api.runItems(selectedRunId), api.runAgreement(selectedRunId)])
      .then(([items, metrics]) => {
        if (active) {
          setAnnotations(items);
          setAgreement(metrics);
          setSelectedId((current) => current || items[0]?.prompt_id || null);
        }
      })
      .catch((err) => { if (active) setStatus(err.message); });
    return () => { active = false; };
  }, [refreshVersion, selectedRunId]);

  useEffect(() => {
    setRunNameDraft(selectedRun?.name || '');
  }, [selectedRun?.name]);

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

  useEffect(() => {
    setOverrideOpen(false);
    setOverrideStatus('');
  }, [selectedId]);

  async function downloadCsv() {
    if (!selectedRunId) return;
    try {
      const blob = await api.exportLabelsCsv(selectedRunId, true);
      download(blob, 'labels.csv');
    } catch (err) {
      setStatus(err.message);
    }
  }

  async function downloadJson() {
    if (!selectedRunId) return;
    try {
      const labels = await api.exportRunLabels(selectedRunId, true);
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

  async function saveRunName(event) {
    event.preventDefault();
    if (!selectedRunId || !runNameDraft.trim()) return;
    try {
      setSavingRunName(true);
      const updated = await api.updateRun(selectedRunId, { name: runNameDraft.trim() });
      setRuns((current) => current.map((run) => (run.run_id === updated.run_id ? updated : run)));
      setStatus('Run renamed.');
      onDataChanged();
    } catch (err) {
      setStatus(err.message);
    } finally {
      setSavingRunName(false);
    }
  }

  async function retryProviderFailures() {
    if (!selectedRunId) return;
    try {
      setRetrying(true);
      const response = await api.retryProviderFailures(selectedRunId);
      const [items, metrics, runsList] = await Promise.all([
        api.runItems(selectedRunId),
        api.runAgreement(selectedRunId),
        api.listRuns(),
      ]);
      setAnnotations(items);
      setAgreement(metrics);
      setRuns(runsList);
      setImportedAnalysis(null);
      setStatus(`Retried ${response.progress.completed} items; ${response.progress.failed} failed.`);
      onDataChanged();
    } catch (err) {
      setStatus(err.message);
    } finally {
      setRetrying(false);
    }
  }

  async function resumeRun() {
    if (!selectedRunId) return;
    try {
      setResuming(true);
      const response = await api.resumeRun(selectedRunId);
      const [items, metrics, runsList] = await Promise.all([
        api.runItems(selectedRunId),
        api.runAgreement(selectedRunId),
        api.listRuns(),
      ]);
      setAnnotations(items);
      setAgreement(metrics);
      setRuns(runsList);
      setImportedAnalysis(null);
      setStatus(`Resumed ${response.progress.completed} rows; ${response.progress.failed} failed.`);
      onDataChanged();
    } catch (err) {
      setStatus(err.message);
    } finally {
      setResuming(false);
    }
  }

  async function deleteSelectedRun() {
    if (!selectedRunId || !selectedRun) return;
    const confirmed = window.confirm(`Delete run ${selectedRun.name}? This cannot be undone.`);
    if (!confirmed) return;

    try {
      await api.deleteRun(selectedRunId);
      const nextRuns = runs.filter((run) => run.run_id !== selectedRunId);
      setRuns(nextRuns);
      setAnnotations([]);
      setAgreement(null);
      setImportedAnalysis(null);
      setSelectedId(null);
      onRunSelected(nextRuns[0]?.run_id || null);
      setStatus(`Deleted run ${selectedRun.name}.`);
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
      await api.deleteAnnotation(selectedRunId, item.prompt_id);
      const next = annotations.filter((entry) => entry.prompt_id !== item.prompt_id);
      setAnnotations(next);
      setSelectedId((current) => {
        if (current !== item.prompt_id) return current;
        return next[0]?.prompt_id || null;
      });
      setImportedAnalysis(null);
      const metrics = selectedRunId ? await api.runAgreement(selectedRunId) : null;
      setAgreement(metrics);
      setStatus(`Deleted ${item.prompt_id}.`);
      onDataChanged();
    } catch (err) {
      setStatus(err.message);
    } finally {
      setDeletingId(null);
    }
  }

  async function saveOverride(payload) {
    try {
      setOverrideStatus('Saving override...');
      const updated = await api.humanReview(payload);
      setAnnotations((current) => current.map((item) => (item.prompt_id === updated.prompt_id ? updated : item)));
      const [metrics, runsList] = await Promise.all([
        api.runAgreement(selectedRunId),
        api.listRuns(),
      ]);
      setAgreement(metrics);
      setRuns(runsList);
      setImportedAnalysis(null);
      setOverrideStatus('Override saved.');
      onDataChanged();
    } catch (err) {
      setOverrideStatus(err.message);
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
          <div>
            <h2>Annotation results</h2>
            <p className="muted">{selectedRun ? selectedRun.name : 'Select a run'} · {filtered.length} of {annotations.length} items</p>
          </div>
          <div className="button-row">
            {annotations.some((item) => effectiveLabel(item) === 'needs_human_review') && <button type="button" onClick={onReview}>Review unresolved</button>}
            <button type="button" className="secondary" disabled={!selectedRunId} onClick={downloadJson}>Export JSON</button>
            <button type="button" className="secondary" disabled={!selectedRunId} onClick={downloadCsv}>Export CSV</button>
            <label className="upload-button">Analyze CSV<input type="file" accept=".csv,text/csv" onChange={analyzeCsv} /></label>
            {selectedRun?.provider_failed > 0 && (
              <button type="button" className="secondary" disabled={retrying} onClick={retryProviderFailures}>
                {retrying ? 'Retrying...' : 'Retry provider failures'}
              </button>
            )}
            {selectedRun?.resumable_items > 0 && (
              <button type="button" className="secondary" disabled={resuming} onClick={resumeRun}>
                {resuming ? 'Resuming...' : 'Resume run'}
              </button>
            )}
            <button type="button" className="secondary danger-button" disabled={!selectedRunId} onClick={deleteSelectedRun}>Delete run</button>
          </div>
        </div>

        <div className="run-selector">
          <label htmlFor="run-select">Run</label>
          <select
            id="run-select"
            value={selectedRunId || ''}
            onChange={(event) => onRunSelected(event.target.value || null)}
          >
            <option value="">No run selected</option>
            {runs.map((run) => (
              <option key={run.run_id} value={run.run_id}>
                {run.name} · {run.total_items} items
              </option>
            ))}
          </select>
        </div>

        {selectedRun && (
          <>
            <form className="run-rename" onSubmit={saveRunName}>
              <label htmlFor="run-name">Run name</label>
              <input id="run-name" value={runNameDraft} onChange={(event) => setRunNameDraft(event.target.value)} />
              <button type="submit" className="secondary" disabled={savingRunName || !runNameDraft.trim()}>
                {savingRunName ? 'Saving...' : 'Rename'}
              </button>
            </form>
            <div className="run-meta">
              <span>Status: <strong>{selectedRun.status}</strong></span>
              <span>Task: <strong>{formatTaskType(selectedRun.task_type)}</strong></span>
              <span>Completed: <strong>{selectedRun.completed_items}/{selectedRun.total_items}</strong></span>
              <span>Failed rows: <strong>{selectedRun.failed_items}</strong></span>
              <span>Resumable: <strong>{selectedRun.resumable_items}</strong></span>
              <span>Provider failed: <strong>{selectedRun.provider_failed}</strong></span>
              <span>Disagreement: <strong>{selectedRun.disagreement}</strong></span>
              <span>Abstention: <strong>{selectedRun.abstention}</strong></span>
              <span>Ambiguous: <strong>{selectedRun.ambiguous}</strong></span>
              <span>Created: <strong>{selectedRun.created_at}</strong></span>
              <span>Completed at: <strong>{selectedRun.completed_at || 'n/a'}</strong></span>
              <span>Source: <strong>{selectedRun.source_filename || 'n/a'}</strong></span>
              <span>Policy: <strong>{selectedRun.policy_version}</strong></span>
              <span>Rule: <strong>{selectedRun.decision_rule_version}</strong></span>
              <span>Models: <strong>{selectedRun.model_config_json?.models?.join(', ') || 'n/a'}</strong></span>
            </div>
          </>
        )}

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
            <div><span>Failed rows</span><strong>{formatRatio(displayedCounts.failed, displayedTotal)}</strong></div>
          </div>
        )}
        <div className="filter-row">
          {['all', 'safe', 'unsafe', 'needs_human_review', 'failed'].map((value) => (
            <button key={value} type="button" className={filter === value ? 'filter active' : 'filter'} onClick={() => setFilter(value)}>{value === 'all' ? 'All' : displayLabel(value)}</button>
          ))}
        </div>
        {status && <div className="alert error">{status}</div>}
        <div className="table-wrap" tabIndex={0} onKeyDown={handleResultTableKeyDown}>
          <table className="results-table">
            <thead><tr><th>Prompt ID</th><th>Final label</th><th>Source</th><th>Category</th><th>Status</th><th>Reason</th><th>Updated</th><th>Actions</th></tr></thead>
            <tbody>
              {filtered.map((item) => {
                const review = item.human_reviews?.at(-1);
                return (
                  <tr key={item.prompt_id} className={selectedId === item.prompt_id ? 'selected-row' : ''} onClick={() => setSelectedId(item.prompt_id)}>
                    <td>{item.prompt_id}</td>
                    <td><Badge label={effectiveLabel(item)} /></td>
                    <td>{review ? 'human' : 'AI annotators'}</td>
                    <td>{review?.unsafe_category || item.adjudication?.unsafe_category || 'none'}</td>
                    <td>{item.error_message && !item.adjudication ? 'failed' : (review ? 'reviewed' : item.adjudication?.decision_type)}</td>
                    <td>{formatReason(item.review_reason_type)}</td>
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
            {selected.review_reason_type !== 'none' && <p className="muted">Review reason: {formatReason(selected.review_reason_type)}</p>}
            <div className="button-row inspector-actions">
              {effectiveLabel(selected) === 'needs_human_review' && <button type="button" onClick={onReview}>Open review queue</button>}
              <button type="button" className="secondary" onClick={() => setOverrideOpen((value) => !value)}>
                {selected.human_reviews?.length ? 'Edit override' : 'Override label'}
              </button>
            </div>
            {overrideOpen && (
              <HumanLabelForm
                annotation={selected}
                submitLabel="Save override"
                status={overrideStatus}
                onSubmit={saveOverride}
              />
            )}
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

function formatTaskType(taskType) {
  return (taskType || '').replaceAll('_', ' ');
}

function formatReason(reasonType) {
  return reasonType === 'none' ? 'none' : (reasonType || '').replaceAll('_', ' ');
}

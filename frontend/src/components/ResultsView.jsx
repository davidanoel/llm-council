import { useEffect, useState } from 'react';
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
  const [pageInfo, setPageInfo] = useState({ total: 0, page: 1, page_size: 100, total_pages: 0 });
  const [filter, setFilter] = useState('all');
  const [reviewReason, setReviewReason] = useState('all');
  const [labelSource, setLabelSource] = useState('all');
  const [sort, setSort] = useState('row_number');
  const [direction, setDirection] = useState('asc');
  const [pageSize, setPageSize] = useState(100);
  const [searchInput, setSearchInput] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedId, setSelectedId] = useState(null);
  const [agreement, setAgreement] = useState(null);
  const [exportPreview, setExportPreview] = useState(null);
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
  const selected = annotations.find((item) => item.prompt_id === selectedId);
  const displayedAgreement = importedAnalysis?.agreement || agreement;
  const displayedTotal = importedAnalysis?.total_items ?? exportPreview?.total_items ?? 0;
  const displayedCounts = importedAnalysis ? {
    safe: importedAnalysis.safe_items,
    unsafe: importedAnalysis.unsafe_items,
    unresolved: importedAnalysis.unresolved_items,
    humanReviewed: importedAnalysis.human_review_items,
    failed: 0,
  } : {
    safe: exportPreview?.safe_items || 0,
    unsafe: exportPreview?.unsafe_items || 0,
    unresolved: exportPreview?.unresolved_items || 0,
    humanReviewed: exportPreview?.human_reviewed_items || 0,
    failed: exportPreview?.failed_items || 0,
  };

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
      setPageInfo({ total: 0, page: 1, page_size: pageSize, total_pages: 0 });
      setAgreement(null);
      setExportPreview(null);
      setSelectedId(null);
      return () => { active = false; };
    }

    Promise.all([
      api.runItemsPage(selectedRunId, {
        page: pageInfo.page,
        page_size: pageSize,
        label: filter,
        review_reason: reviewReason,
        label_source: labelSource,
        search: searchQuery,
        sort,
        direction,
      }),
      api.runAgreement(selectedRunId),
      api.exportPreview(selectedRunId),
    ])
      .then(([pageData, metrics, preview]) => {
        if (active) {
          setAnnotations(pageData.items);
          setPageInfo({
            total: pageData.total,
            page: pageData.page,
            page_size: pageData.page_size,
            total_pages: pageData.total_pages,
          });
          setAgreement(metrics);
          setExportPreview(preview);
          setSelectedId((current) => (
            pageData.items.some((item) => item.prompt_id === current)
              ? current
              : pageData.items[0]?.prompt_id || null
          ));
        }
      })
      .catch((err) => { if (active) setStatus(err.message); });
    return () => { active = false; };
  }, [refreshVersion, selectedRunId, pageInfo.page, pageSize, filter, reviewReason, labelSource, searchQuery, sort, direction]);

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
    setPageInfo((current) => ({ ...current, page: 1 }));
  }, [filter, reviewReason, labelSource, searchQuery, sort, direction, pageSize]);

  useEffect(() => {
    setOverrideOpen(false);
    setOverrideStatus('');
  }, [selectedId]);

  async function downloadCsv() {
    if (!selectedRunId) return;
    try {
      const blob = await api.exportLabelsCsv(selectedRunId, true);
      download(blob, exportFilename(selectedRun, 'labels', 'csv'));
    } catch (err) {
      setStatus(err.message);
    }
  }

  async function downloadJson() {
    if (!selectedRunId) return;
    try {
      const labels = await api.exportRunLabels(selectedRunId, true);
      download(new Blob([JSON.stringify(labels, null, 2)], { type: 'application/json' }), exportFilename(selectedRun, 'labels', 'json'));
    } catch (err) {
      setStatus(err.message);
    }
  }

  async function downloadManifest() {
    if (!selectedRunId) return;
    try {
      const manifest = await api.exportManifest(selectedRunId);
      download(
        new Blob([JSON.stringify(manifest, null, 2)], { type: 'application/json' }),
        exportFilename(selectedRun, 'manifest', 'json'),
      );
    } catch (err) {
      setStatus(err.message);
    }
  }

  async function refreshCurrentPage(includeRuns = false) {
    const requests = [
      api.runItemsPage(selectedRunId, {
        page: pageInfo.page,
        page_size: pageSize,
        label: filter,
        review_reason: reviewReason,
        label_source: labelSource,
        search: searchQuery,
        sort,
        direction,
      }),
      api.runAgreement(selectedRunId),
      api.exportPreview(selectedRunId),
    ];
    if (includeRuns) requests.push(api.listRuns());
    const [pageData, metrics, preview, runsList] = await Promise.all(requests);
    setAnnotations(pageData.items);
    setPageInfo({
      total: pageData.total,
      page: pageData.page,
      page_size: pageData.page_size,
      total_pages: pageData.total_pages,
    });
    setSelectedId((current) => (
      pageData.items.some((item) => item.prompt_id === current)
        ? current
        : pageData.items[0]?.prompt_id || null
    ));
    setAgreement(metrics);
    setExportPreview(preview);
    if (runsList) setRuns(runsList);
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
      await refreshCurrentPage(true);
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
      await refreshCurrentPage(true);
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
      setExportPreview(null);
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
      await refreshCurrentPage(false);
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
      await refreshCurrentPage(true);
      setImportedAnalysis(null);
      setOverrideStatus('Override saved.');
      onDataChanged();
    } catch (err) {
      setOverrideStatus(err.message);
    }
  }

  function handleResultTableKeyDown(event) {
    if (!annotations.length) return;

    const currentIndex = Math.max(0, annotations.findIndex((item) => item.prompt_id === selectedId));

    if (event.key === 'ArrowDown') {
      event.preventDefault();
      const nextIndex = Math.min(annotations.length - 1, currentIndex + 1);
      setSelectedId(annotations[nextIndex].prompt_id);
      return;
    }

    if (event.key === 'ArrowUp') {
      event.preventDefault();
      const nextIndex = Math.max(0, currentIndex - 1);
      setSelectedId(annotations[nextIndex].prompt_id);
    }
  }

  return (
    <section className="results-split">
      <section className="panel results-panel results-list-panel">
        <div className="results-toolbar">
          <div>
            <h2>Annotation results</h2>
            <p className="muted">{selectedRun ? selectedRun.name : 'Select a run'} · {annotations.length} shown of {pageInfo.total} matching rows</p>
          </div>
          <div className="button-row">
            {exportPreview?.unresolved_items > 0 && <button type="button" title="Review unresolved" aria-label="Review unresolved" onClick={onReview}>Review</button>}
            <button type="button" className="secondary compact-button" title="Export JSON" disabled={!selectedRunId} onClick={downloadJson}>JSON</button>
            <button type="button" className="secondary compact-button" title="Export CSV" disabled={!selectedRunId} onClick={downloadCsv}>CSV</button>
            <button type="button" className="secondary compact-button" title="Export manifest" disabled={!selectedRunId} onClick={downloadManifest}>Manifest</button>
            <label className="upload-button compact-button" title="Analyze exported CSV">Analyze<input type="file" accept=".csv,text/csv" onChange={analyzeCsv} /></label>
            {selectedRun?.provider_failed > 0 && (
              <button type="button" className="secondary compact-button" title="Retry provider failures" disabled={retrying} onClick={retryProviderFailures}>
                {retrying ? '...' : 'Retry'}
              </button>
            )}
            {selectedRun?.resumable_items > 0 && (
              <button type="button" className="secondary compact-button" title="Resume failed rows" disabled={resuming} onClick={resumeRun}>
                {resuming ? '...' : 'Resume'}
              </button>
            )}
            <button type="button" className="secondary danger-button compact-button" title="Delete run" disabled={!selectedRunId} onClick={deleteSelectedRun}>Delete</button>
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
              <span>Needs review: <strong>{selectedRun.human_review}</strong></span>
              <span>Failed rows: <strong>{selectedRun.failed_items}</strong></span>
              <span>Resumable: <strong>{selectedRun.resumable_items}</strong></span>
              <span>Provider failed: <strong>{selectedRun.provider_failed}</strong></span>
            </div>
            <details className="run-details">
              <summary>Run details</summary>
              <div className="run-meta detail-meta">
                <span>Source: <strong>{selectedRun.source_filename || 'n/a'}</strong></span>
                <span>Created: <strong>{selectedRun.created_at}</strong></span>
                <span>Completed at: <strong>{selectedRun.completed_at || 'n/a'}</strong></span>
                <span>Policy: <strong>{selectedRun.policy_version}</strong></span>
                <span>Rule: <strong>{selectedRun.decision_rule_version}</strong></span>
                <span>Models: <strong>{selectedRun.model_config_json?.models?.join(', ') || 'n/a'}</strong></span>
              </div>
            </details>
          </>
        )}

        {importedAnalysis && (
          <div className="metric-source">Metrics from <strong>{importedAnalysis.fileName}</strong><button type="button" className="filter" onClick={() => setImportedAnalysis(null)}>Use current data</button></div>
        )}
        {exportPreview && !importedAnalysis && (
          <div className="metric-section">
            <h3>Run health</h3>
            <div className="metrics-grid">
              <div><span>Total rows</span><strong>{exportPreview.total_items}</strong></div>
              <div><span>AI labeled</span><strong>{formatRatio(exportPreview.ai_labeled_items, exportPreview.total_items)}</strong></div>
              <div><span>Needs review</span><strong>{formatRatio(exportPreview.unresolved_items, exportPreview.total_items)}</strong></div>
              <div><span>Human reviewed</span><strong>{formatRatio(exportPreview.human_reviewed_items, exportPreview.total_items)}</strong></div>
              <div><span>Failed</span><strong>{formatRatio(exportPreview.failed_items, exportPreview.total_items)}</strong></div>
              <div><span>Exportable</span><strong>{formatRatio(exportPreview.exportable_items, exportPreview.total_items)}</strong></div>
            </div>
          </div>
        )}
        {displayedTotal > 0 && (
          <div className="metric-section">
            <h3>Label distribution</h3>
            <div className="metrics-grid">
            <div><span>Final safe rate</span><strong>{formatRatio(displayedCounts.safe, displayedTotal)}</strong></div>
            <div><span>Final unsafe rate</span><strong>{formatRatio(displayedCounts.unsafe, displayedTotal)}</strong></div>
              <div><span>Unresolved review</span><strong>{formatRatio(displayedCounts.unresolved, displayedTotal)}</strong></div>
              <div><span>Human reviewed</span><strong>{formatRatio(displayedCounts.humanReviewed, displayedTotal)}</strong></div>
            <div><span>Failed rows</span><strong>{formatRatio(displayedCounts.failed, displayedTotal)}</strong></div>
          </div>
          </div>
        )}
        {displayedAgreement && (
          <details className="agreement-details">
            <summary>Agreement details</summary>
            {displayedAgreement.complete_items === 0 ? (
              <p className="muted agreement-note">
                Agreement is unavailable because no rows have three successful model votes. This usually means provider or parse failures; retry provider failures or run the demo with the mock provider.
              </p>
            ) : (
              <div className="metrics-grid agreement-summary">
                <div><span>Pairwise agreement</span><strong>{formatPercent(displayedAgreement.observed_agreement)}</strong><small>Average model-pair agreement</small></div>
                <div><span>All 3 matched</span><strong>{formatPercent(displayedAgreement.unanimous_rate)}</strong><small>Complete panels only</small></div>
                <div><span>Complete vote panels</span><strong>{formatRatio(displayedAgreement.complete_items, displayedTotal)}</strong><small>All 3 votes succeeded</small></div>
                <div><span>Fleiss kappa</span><strong>{displayedAgreement.fleiss_kappa ?? 'N/A'}</strong><small>Chance-corrected; unstable when labels are imbalanced</small></div>
              </div>
            )}
          </details>
        )}
        <div className="filter-row result-browser-controls">
          {['all', 'safe', 'unsafe', 'needs_human_review', 'failed'].map((value) => (
            <button key={value} type="button" className={filter === value ? 'filter active' : 'filter'} onClick={() => setFilter(value)}>{value === 'all' ? 'All' : displayLabel(value)}</button>
          ))}
          <select aria-label="Review reason" value={reviewReason} onChange={(event) => setReviewReason(event.target.value)}>
            <option value="all">Any reason</option>
            <option value="provider_failure">Provider failure</option>
            <option value="disagreement">Disagreement</option>
            <option value="abstention">Abstention</option>
            <option value="ambiguous">Ambiguous</option>
          </select>
          <select aria-label="Label source" value={labelSource} onChange={(event) => setLabelSource(event.target.value)}>
            <option value="all">Any source</option>
            <option value="ai">AI</option>
            <option value="human">Human</option>
          </select>
          <select aria-label="Sort" value={sort} onChange={(event) => setSort(event.target.value)}>
            <option value="row_number">Row order</option>
            <option value="prompt_id">Prompt ID</option>
            <option value="updated_at">Updated</option>
            <option value="effective_label">Label</option>
          </select>
          <button
            type="button"
            className="filter"
            title={`Sort ${direction === 'asc' ? 'ascending' : 'descending'}`}
            aria-label={`Sort ${direction === 'asc' ? 'ascending' : 'descending'}`}
            onClick={() => setDirection((value) => (value === 'asc' ? 'desc' : 'asc'))}
          >
            {direction === 'asc' ? 'Asc' : 'Desc'}
          </button>
        </div>
        <div className="search-row">
          <label htmlFor="results-search" className="search-label">Search prompts</label>
          <input
            id="results-search"
            type="search"
            placeholder="Search by prompt id, text, response, or error"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
          />
        </div>
        {status && <div className="alert error">{status}</div>}
        <div className="table-wrap" tabIndex={0} onKeyDown={handleResultTableKeyDown}>
          <table className="results-table">
            <thead><tr><th>Prompt ID</th><th>Final label</th><th>Source</th><th>Category</th><th>Status</th><th>Reason</th><th>Updated</th><th>Actions</th></tr></thead>
            <tbody>
              {annotations.map((item) => {
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
                        {deletingId === item.prompt_id ? '...' : 'Del'}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="pagination-row">
          <span>
            Page <strong>{pageInfo.total_pages ? pageInfo.page : 0}</strong> of <strong>{pageInfo.total_pages}</strong>
          </span>
          <label>
            Rows
            <select value={pageSize} onChange={(event) => setPageSize(Number(event.target.value))}>
              {[50, 100, 250].map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
          <div className="button-row">
            <button
              type="button"
              className="secondary compact-button"
              title="Previous page"
              disabled={pageInfo.page <= 1}
              onClick={() => setPageInfo((current) => ({ ...current, page: Math.max(1, current.page - 1) }))}
            >
              Prev
            </button>
            <button
              type="button"
              className="secondary compact-button"
              title="Next page"
              disabled={!pageInfo.total_pages || pageInfo.page >= pageInfo.total_pages}
              onClick={() => setPageInfo((current) => ({ ...current, page: Math.min(current.total_pages, current.page + 1) }))}
            >
              Next
            </button>
          </div>
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

function exportFilename(run, kind, extension) {
  return `${safeFilename(run?.name || 'annotation-run')}-${kind}.${extension}`;
}

function safeFilename(value) {
  const cleaned = value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return cleaned || 'annotation-run';
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

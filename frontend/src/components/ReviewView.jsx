import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../api';
import { AnnotationContent, Badge, DecisionSummary, VoteDetails } from './AnnotationDetails';
import HumanLabelForm from './HumanLabelForm';

export default function ReviewView({ refreshVersion, selectedRunId, onSaved }) {
  const [queue, setQueue] = useState([]);
  const [run, setRun] = useState(null);
  const [index, setIndex] = useState(0);
  const [reasonFilter, setReasonFilter] = useState('all');
  const [status, setStatus] = useState('');
  const indexRef = useRef(0);
  const scopeRef = useRef({ selectedRunId: null, reasonFilter: 'all' });
  const current = queue[index];

  const voteCounts = useMemo(() => {
    const counts = { safe: 0, unsafe: 0, needs_human_review: 0 };
    current?.votes?.forEach((vote) => { counts[vote.label] += 1; });
    return counts;
  }, [current]);

  const loadQueue = useCallback(async (nextIndex = 0) => {
    if (!selectedRunId) {
      setQueue([]);
      return;
    }
    try {
      const [items, runSummary] = await Promise.all([
        api.runReviewQueue(selectedRunId, reasonFilter),
        api.getRun(selectedRunId),
      ]);
      setQueue(items);
      setRun(runSummary);
      setIndex(Math.min(nextIndex, Math.max(items.length - 1, 0)));
    } catch (err) {
      setStatus(err.message);
    }
  }, [selectedRunId, reasonFilter]);

  useEffect(() => {
    indexRef.current = index;
  }, [index]);

  useEffect(() => {
    let active = true;
    if (!selectedRunId) {
      setQueue([]);
      setRun(null);
      setIndex(0);
      scopeRef.current = { selectedRunId: null, reasonFilter };
      return () => { active = false; };
    }
    const scopeChanged = (
      scopeRef.current.selectedRunId !== selectedRunId
      || scopeRef.current.reasonFilter !== reasonFilter
    );
    const nextIndex = scopeChanged ? 0 : indexRef.current;
    scopeRef.current = { selectedRunId, reasonFilter };

    Promise.all([api.runReviewQueue(selectedRunId, reasonFilter), api.getRun(selectedRunId)])
      .then(([items, runSummary]) => {
        if (active) {
          setQueue(items);
          setRun(runSummary);
          setIndex(Math.min(nextIndex, Math.max(items.length - 1, 0)));
        }
      })
      .catch((err) => { if (active) setStatus(err.message); });
    return () => { active = false; };
  }, [refreshVersion, selectedRunId, reasonFilter]);

  useEffect(() => {
    function handleKeyDown(event) {
      if (!queue.length) return;
      if (isEditableTarget(event.target)) return;
      if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
        event.preventDefault();
        setIndex((currentIndex) => Math.max(0, currentIndex - 1));
      }
      if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
        event.preventDefault();
        setIndex((currentIndex) => Math.min(queue.length - 1, currentIndex + 1));
      }
    }

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [queue.length]);

  async function saveAndNext(payload) {
    if (!current) return;
    setStatus('Saving review...');
    try {
      await api.humanReview(payload);
      await loadQueue(index);
      onSaved();
      setStatus('Review saved.');
    } catch (err) {
      setStatus(err.message);
    }
  }

  if (!current) {
    return (
      <section className="panel empty-view">
        <h2>Review queue</h2>
        <ReasonFilters active={reasonFilter} counts={run} onChange={setReasonFilter} />
        <p>No prompts currently need human review.</p>
      </section>
    );
  }

  return (
    <section className="panel review-workspace">
      <div className="review-header">
        <div>
          <h2>Human review</h2>
          <span>Item {index + 1} of {queue.length} · {formatReason(current.review_reason_type)}</span>
        </div>
        <div className="button-row">
          <button type="button" className="secondary" disabled={index === 0} onClick={() => setIndex(index - 1)}>Previous</button>
          <button type="button" className="secondary" disabled={index >= queue.length - 1} onClick={() => setIndex(index + 1)}>Next</button>
        </div>
      </div>

      <ReasonFilters active={reasonFilter} counts={run} onChange={setReasonFilter} />

      <AnnotationContent annotation={current} />

      {current.suggested_label && (
        <p className="suggestion-hint">
          Suggested label: <Badge label={current.suggested_label} />
          {current.suggested_label === 'unsafe' ? ` ${current.suggested_unsafe_category}` : ''}
        </p>
      )}

      <HumanLabelForm annotation={current} submitLabel="Save and next" status={status} onSubmit={saveAndNext} />

      <details className="model-details">
        <summary>Show AI suggestion and model votes</summary>
        <DecisionSummary annotation={current} />
        <div className="vote-strip">
          <span>Votes</span>
          <Badge label="safe" /> {voteCounts.safe}
          <Badge label="unsafe" /> {voteCounts.unsafe}
          <Badge label="needs_human_review" /> {voteCounts.needs_human_review}
        </div>
        <VoteDetails annotation={current} />
      </details>
    </section>
  );
}

function ReasonFilters({ active, counts, onChange }) {
  const filters = [
    ['all', 'All', counts?.human_review || 0],
    ['provider_failure', 'Provider failures', counts?.provider_failed || 0],
    ['disagreement', 'Disagreement', counts?.disagreement || 0],
    ['abstention', 'Abstention', counts?.abstention || 0],
    ['ambiguous', 'Ambiguous', counts?.ambiguous || 0],
  ];
  return (
    <div className="filter-row compact-filters">
      {filters.map(([value, label, count]) => (
        <button key={value} type="button" className={active === value ? 'filter active' : 'filter'} onClick={() => onChange(value)}>
          {label} ({count})
        </button>
      ))}
    </div>
  );
}

function formatReason(reasonType) {
  return (reasonType || 'ambiguous').replaceAll('_', ' ');
}

function isEditableTarget(target) {
  return ['INPUT', 'TEXTAREA', 'SELECT'].includes(target?.tagName);
}

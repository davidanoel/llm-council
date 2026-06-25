import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import { AnnotationContent, Badge, DecisionSummary, VoteDetails } from './AnnotationDetails';
import HumanLabelForm from './HumanLabelForm';

export default function ReviewView({ refreshVersion, selectedRunId, onSaved }) {
  const [queue, setQueue] = useState([]);
  const [run, setRun] = useState(null);
  const [index, setIndex] = useState(0);
  const [reasonFilter, setReasonFilter] = useState('all');
  const [status, setStatus] = useState('');
  const current = queue[index];

  const voteCounts = useMemo(() => {
    const counts = { safe: 0, unsafe: 0, needs_human_review: 0 };
    current?.votes?.forEach((vote) => { counts[vote.label] += 1; });
    return counts;
  }, [current]);

  const loadQueue = useCallback(async () => {
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
      setIndex(0);
    } catch (err) {
      setStatus(err.message);
    }
  }, [selectedRunId, reasonFilter]);

  useEffect(() => {
    let active = true;
    if (!selectedRunId) {
      setQueue([]);
      setRun(null);
      return () => { active = false; };
    }
    Promise.all([api.runReviewQueue(selectedRunId, reasonFilter), api.getRun(selectedRunId)])
      .then(([items, runSummary]) => {
        if (active) {
          setQueue(items);
          setRun(runSummary);
          setIndex(0);
        }
      })
      .catch((err) => { if (active) setStatus(err.message); });
    return () => { active = false; };
  }, [refreshVersion, selectedRunId, reasonFilter]);

  async function saveAndNext(payload) {
    if (!current) return;
    setStatus('Saving review...');
    try {
      await api.humanReview(payload);
      await loadQueue();
      onSaved();
      setStatus('Review saved.');
    } catch (err) {
      setStatus(err.message);
    }
  }

  async function acceptSuggestion() {
    if (!current?.suggested_label) return;
    await saveAndNext({
      prompt_id: current.prompt_id,
      run_id: current.run_id,
      label: current.suggested_label,
      unsafe_category: current.suggested_label === 'unsafe' ? current.suggested_unsafe_category : 'none',
      rationale: `Accepted AI suggestion for ${formatReason(current.review_reason_type)}.`,
      reviewer: 'local-user',
    });
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
        <div className="suggestion-box">
          <span>Suggestion: <strong>{current.suggested_label}</strong>{current.suggested_label === 'unsafe' ? ` · ${current.suggested_unsafe_category}` : ''}</span>
          <button type="button" onClick={acceptSuggestion}>Accept {current.suggested_label}</button>
        </div>
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

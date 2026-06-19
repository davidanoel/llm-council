import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import { AnnotationContent, Badge, DecisionSummary, VoteDetails } from './AnnotationDetails';
import { UNSAFE_CATEGORIES } from './annotationUtils';

export default function ReviewView({ refreshVersion, onSaved }) {
  const [queue, setQueue] = useState([]);
  const [index, setIndex] = useState(0);
  const [label, setLabel] = useState('safe');
  const [category, setCategory] = useState('other');
  const [rationale, setRationale] = useState('');
  const [reviewer, setReviewer] = useState('local-user');
  const [status, setStatus] = useState('');
  const current = queue[index];

  const voteCounts = useMemo(() => {
    const counts = { safe: 0, unsafe: 0, needs_human_review: 0 };
    current?.votes?.forEach((vote) => { counts[vote.label] += 1; });
    return counts;
  }, [current]);

  const loadQueue = useCallback(async () => {
    try {
      const items = await api.reviewQueue();
      setQueue(items);
      setIndex(0);
    } catch (err) {
      setStatus(err.message);
    }
  }, []);

  useEffect(() => {
    let active = true;
    api.reviewQueue()
      .then((items) => {
        if (active) {
          setQueue(items);
          setIndex(0);
        }
      })
      .catch((err) => { if (active) setStatus(err.message); });
    return () => { active = false; };
  }, [refreshVersion]);

  async function saveAndNext() {
    if (!current) return;
    setStatus('Saving review...');
    try {
      await api.humanReview({
        prompt_id: current.prompt_id,
        label,
        unsafe_category: label === 'unsafe' ? category : 'none',
        rationale,
        reviewer,
      });
      setRationale('');
      setCategory('other');
      await loadQueue();
      onSaved();
      setStatus('Review saved.');
    } catch (err) {
      setStatus(err.message);
    }
  }

  if (!current) {
    return <section className="panel empty-view"><h2>Review queue</h2><p>No prompts currently need human review.</p></section>;
  }

  return (
    <section className="panel review-workspace">
      <div className="review-header">
        <div><h2>Human review</h2><span>Item {index + 1} of {queue.length}</span></div>
        <div className="button-row">
          <button type="button" className="secondary" disabled={index === 0} onClick={() => setIndex(index - 1)}>Previous</button>
          <button type="button" className="secondary" disabled={index >= queue.length - 1} onClick={() => setIndex(index + 1)}>Next</button>
        </div>
      </div>

      <AnnotationContent annotation={current} />

      <div className="review-form">
        <fieldset>
          <legend>Set final label</legend>
          <div className="segmented">
            <button type="button" className={label === 'safe' ? 'selected safe-choice' : ''} onClick={() => setLabel('safe')}>Safe</button>
            <button type="button" className={label === 'unsafe' ? 'selected unsafe-choice' : ''} onClick={() => setLabel('unsafe')}>Unsafe</button>
          </div>
        </fieldset>
        {label === 'unsafe' && <label>Unsafe category<select value={category} onChange={(event) => setCategory(event.target.value)}>{UNSAFE_CATEGORIES.filter((item) => item !== 'none').map((item) => <option key={item}>{item}</option>)}</select></label>}
        <label>Rationale<textarea rows={4} value={rationale} onChange={(event) => setRationale(event.target.value)} /></label>
        <label>Reviewer<input value={reviewer} onChange={(event) => setReviewer(event.target.value)} /></label>
        <button type="button" onClick={saveAndNext}>Save and next</button>
        {status && <span className="muted">{status}</span>}
      </div>

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

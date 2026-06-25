import { useEffect, useState } from 'react';
import { UNSAFE_CATEGORIES } from './annotationUtils';

export default function HumanLabelForm({
  annotation,
  submitLabel = 'Save',
  status = '',
  onSubmit,
}) {
  const latestReview = annotation?.human_reviews?.at(-1);
  const suggestedLabel = latestReview?.label || annotation?.adjudication?.final_label;
  const [label, setLabel] = useState(suggestedLabel === 'unsafe' ? 'unsafe' : 'safe');
  const [category, setCategory] = useState(latestReview?.unsafe_category || annotation?.adjudication?.unsafe_category || 'other');
  const [rationale, setRationale] = useState('');
  const [reviewer, setReviewer] = useState('local-user');

  useEffect(() => {
    const nextReview = annotation?.human_reviews?.at(-1);
    const nextLabel = nextReview?.label || annotation?.adjudication?.final_label;
    setLabel(nextLabel === 'unsafe' ? 'unsafe' : 'safe');
    setCategory(nextReview?.unsafe_category || annotation?.adjudication?.unsafe_category || 'other');
    setRationale('');
  }, [annotation?.prompt_id, annotation?.updated_at]);

  useEffect(() => {
    function handleKeyDown(event) {
      if (isEditableTarget(event.target)) return;
      const key = event.key.toLowerCase();
      if (key === 's') {
        event.preventDefault();
        setLabel('safe');
      }
      if (key === 'u') {
        event.preventDefault();
        setLabel('unsafe');
      }
      if (event.key === 'Enter') {
        event.preventDefault();
        submit();
      }
    }

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [annotation, label, category, rationale, reviewer]);

  function submit() {
    if (!annotation) return;
    onSubmit({
      prompt_id: annotation.prompt_id,
      run_id: annotation.run_id,
      label,
      unsafe_category: label === 'unsafe' ? category : 'none',
      rationale,
      reviewer,
    });
  }

  return (
    <div className="review-form">
      <fieldset>
        <legend>Set final label</legend>
        <div className="segmented">
          <button type="button" className={label === 'safe' ? 'selected safe-choice' : ''} onClick={() => setLabel('safe')}>Safe</button>
          <button type="button" className={label === 'unsafe' ? 'selected unsafe-choice' : ''} onClick={() => setLabel('unsafe')}>Unsafe</button>
        </div>
      </fieldset>
      {label === 'unsafe' && (
        <label>
          Unsafe category
          <select value={category} onChange={(event) => setCategory(event.target.value)}>
            {UNSAFE_CATEGORIES.filter((item) => item !== 'none').map((item) => <option key={item}>{item}</option>)}
          </select>
        </label>
      )}
      <label>Rationale<textarea rows={4} value={rationale} onChange={(event) => setRationale(event.target.value)} /></label>
      <label>Reviewer<input value={reviewer} onChange={(event) => setReviewer(event.target.value)} /></label>
      <button type="button" onClick={submit}>{submitLabel}</button>
      {status && <span className="muted">{status}</span>}
    </div>
  );
}

function isEditableTarget(target) {
  return ['INPUT', 'TEXTAREA', 'SELECT'].includes(target?.tagName);
}

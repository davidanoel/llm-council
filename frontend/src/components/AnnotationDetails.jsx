import { displayLabel, effectiveLabel } from './annotationUtils';

export function Badge({ label }) {
  return <span className={`badge ${label}`}>{displayLabel(label)}</span>;
}

export function AnnotationContent({ annotation }) {
  const hasResponse = Boolean(annotation?.response_text);
  return (
    <div className="annotation-content">
      <div className="prompt-review">
        <span>{hasResponse ? 'User input (context)' : 'Prompt (classification target)'}</span>
        <p>{annotation.prompt_text}</p>
      </div>
      {hasResponse && (
        <div className="prompt-review response-target">
          <span>Assistant response (classification target)</span>
          <p>{annotation.response_text}</p>
        </div>
      )}
    </div>
  );
}

export function DecisionSummary({ annotation }) {
  if (!annotation?.adjudication) return <p className="muted">No decision available.</p>;
  const review = annotation.human_reviews?.at(-1);
  return (
    <div className="result-card">
      <div className="label-row">
        <Badge label={effectiveLabel(annotation)} />
        <span>{review ? 'Human-reviewed label' : 'Automated label'}</span>
      </div>
      <dl>
        <dt>Final label</dt><dd>{displayLabel(effectiveLabel(annotation))}</dd>
        <dt>Label source</dt><dd>{review ? `Human review by ${review.reviewer}` : 'AI annotator agreement'}</dd>
        <dt>Confidence</dt><dd>{annotation.adjudication.confidence.toFixed(2)}</dd>
        <dt>Category</dt><dd>{review?.unsafe_category || annotation.adjudication.unsafe_category}</dd>
        <dt>Rationale</dt><dd>{review?.rationale || annotation.adjudication.rationale}</dd>
      </dl>
    </div>
  );
}

export function VoteDetails({ annotation }) {
  if (!annotation?.votes?.length) return null;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr><th>Annotator</th><th>Label</th><th>Category</th><th>Confidence</th><th>Rationale</th></tr>
        </thead>
        <tbody>
          {annotation.votes.map((vote) => (
            <tr key={vote.model_name}>
              <td>{vote.model_name}</td>
              <td><Badge label={vote.label} /></td>
              <td>{vote.unsafe_category}</td>
              <td>{vote.confidence.toFixed(2)}</td>
              <td>{vote.rationale}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

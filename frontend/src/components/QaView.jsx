import { useEffect, useMemo, useState } from 'react';
import { api } from '../api';

export default function QaView({ refreshVersion, selectedRunId, onRunSelected }) {
  const [runs, setRuns] = useState([]);
  const [leftRunId, setLeftRunId] = useState(selectedRunId || '');
  const [rightRunId, setRightRunId] = useState('');
  const [leftQa, setLeftQa] = useState(null);
  const [rightQa, setRightQa] = useState(null);
  const [status, setStatus] = useState('');

  useEffect(() => {
    let active = true;
    api.listRuns()
      .then((items) => {
        if (!active) return;
        setRuns(items);
        const nextLeft = selectedRunId || items[0]?.run_id || '';
        setLeftRunId((current) => current || nextLeft);
        setRightRunId((current) => current || items.find((run) => run.run_id !== nextLeft)?.run_id || '');
      })
      .catch((err) => { if (active) setStatus(err.message); });
    return () => { active = false; };
  }, [refreshVersion, selectedRunId]);

  useEffect(() => {
    if (selectedRunId) setLeftRunId(selectedRunId);
  }, [selectedRunId]);

  useEffect(() => {
    loadRunQa(leftRunId, setLeftQa, setStatus);
  }, [leftRunId, refreshVersion]);

  useEffect(() => {
    loadRunQa(rightRunId, setRightQa, setStatus);
  }, [rightRunId, refreshVersion]);

  const rows = useMemo(() => compareRows(leftQa, rightQa), [leftQa, rightQa]);

  if (!runs.length) {
    return (
      <section className="panel empty-view">
        <h2>Dataset QA</h2>
        <p>No runs yet. Upload a CSV to start annotating.</p>
      </section>
    );
  }

  return (
    <section className="view-stack">
      {status && <div className="alert error">{status}</div>}
      <section className="panel">
        <div className="results-toolbar">
          <div>
            <h2>Dataset QA</h2>
            <p className="muted">Check export readiness and compare run-level quality signals.</p>
          </div>
        </div>

        <div className="qa-selectors">
          <RunSelect
            label="Selected run"
            runs={runs}
            value={leftRunId}
            onChange={(runId) => {
              setLeftRunId(runId);
              onRunSelected(runId || null);
            }}
          />
          <RunSelect
            label="Compare with"
            runs={runs}
            value={rightRunId}
            onChange={setRightRunId}
            allowEmpty
          />
        </div>

        {leftQa && (
          <div className="metric-section">
            <h3>{leftQa.run.name}</h3>
            <div className="metrics-grid">
              <Metric label="Total rows" value={leftQa.preview.total_items} />
              <Metric label="Exported rows" value={ratio(leftQa.preview.exportable_items, leftQa.preview.total_items)} />
              <Metric label="Unresolved review" value={ratio(leftQa.preview.unresolved_items, leftQa.preview.total_items)} />
              <Metric label="Failed rows" value={ratio(leftQa.preview.failed_items, leftQa.preview.total_items)} />
              <Metric label="Provider failures" value={ratio(leftQa.run.provider_failed, leftQa.preview.total_items)} />
              <Metric label="Unsafe labels" value={ratio(leftQa.unsafe, leftQa.labelTotal)} />
              <Metric label="Human overrides" value={ratio(leftQa.preview.human_reviewed_items, leftQa.preview.total_items)} />
              <Metric label="Complete panels" value={ratio(leftQa.agreement.complete_items, leftQa.preview.total_items)} />
            </div>
          </div>
        )}

        {leftQa && (
          <div className="metric-section">
            <h3>Calibration</h3>
            <div className="metrics-grid">
              <Metric label="Expected-label coverage" value={ratio(leftQa.calibration.expected_label_items, leftQa.calibration.total_items)} />
              <Metric label="Expected match rate" value={percent(leftQa.calibration.expected_match_rate)} />
              <Metric label="Mismatches" value={leftQa.calibration.mismatch_items} />
              <Metric label="Possible false positives" value={leftQa.calibration.possible_false_positive_items} />
              <Metric label="Possible false negatives" value={leftQa.calibration.possible_false_negative_items} />
            </div>
          </div>
        )}
      </section>

      {leftQa && (
        <section className="panel">
          <h2>Calibration details</h2>
          <div className="qa-grid">
            <SmallCountTable title="Unsafe categories" counts={leftQa.calibration.unsafe_category_counts} />
            <SmallCountTable title="Override directions" counts={leftQa.calibration.override_directions} />
            <SmallCountTable title="Consensus" counts={leftQa.calibration.consensus_counts} labels={CONSENSUS_LABELS} />
          </div>
          <h3>Per-model labels</h3>
          <div className="table-wrap qa-table-wrap">
            <table>
              <thead><tr><th>Model</th><th>Safe</th><th>Unsafe</th><th>Review</th></tr></thead>
              <tbody>
                {Object.entries(leftQa.calibration.per_model_label_counts).map(([model, counts]) => (
                  <tr key={model}>
                    <td>{model}</td>
                    <td>{counts.safe || 0}</td>
                    <td>{counts.unsafe || 0}</td>
                    <td>{counts.needs_human_review || 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <h3>Mismatches</h3>
          {leftQa.calibration.mismatch_examples.length ? (
            <div className="table-wrap qa-table-wrap">
              <table>
                <thead><tr><th>Row</th><th>Prompt ID</th><th>Expected</th><th>Final</th><th>Source</th><th>Category</th><th>Prompt</th></tr></thead>
                <tbody>
                  {leftQa.calibration.mismatch_examples.map((item) => (
                    <tr key={item.prompt_id}>
                      <td>{item.row_number || ''}</td>
                      <td>{item.prompt_id}</td>
                      <td>{item.expected_label}</td>
                      <td>{item.final_label}</td>
                      <td>{item.label_source}</td>
                      <td>{item.unsafe_category}</td>
                      <td>{item.response_text || item.prompt_text || ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="muted">No expected-label mismatches found.</p>
          )}
        </section>
      )}

      <section className="panel">
        <h2>Compare runs</h2>
        {!rightQa ? (
          <p className="muted">Choose a second run to compare.</p>
        ) : (
          <div className="table-wrap qa-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Metric</th>
                  <th>{leftQa?.run.name || 'Selected run'}</th>
                  <th>{rightQa.run.name}</th>
                  <th>Delta</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.label}>
                    <td>{row.label}</td>
                    <td>{row.leftDisplay}</td>
                    <td>{row.rightDisplay}</td>
                    <td>{row.deltaDisplay}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </section>
  );
}

async function loadRunQa(runId, setQa, setStatus) {
  if (!runId) {
    setQa(null);
    return;
  }
  try {
    const [run, preview, agreement, labels, calibration] = await Promise.all([
      api.getRun(runId),
      api.exportPreview(runId),
      api.runAgreement(runId),
      api.exportRunLabels(runId, false),
      api.runCalibration(runId, true),
    ]);
    const safe = labels.filter((label) => label.label === 'safe').length;
    const unsafe = labels.filter((label) => label.label === 'unsafe').length;
    const unresolved = labels.filter((label) => label.label === 'needs_human_review').length;
    setQa({ run, preview, agreement, calibration, labels, safe, unsafe, unresolved, labelTotal: labels.length });
    setStatus('');
  } catch (err) {
    setQa(null);
    setStatus(err.message);
  }
}

function compareRows(leftQa, rightQa) {
  if (!leftQa || !rightQa) return [];
  return [
    countRow('Total rows', leftQa.preview.total_items, rightQa.preview.total_items),
    countRow('Exported rows', leftQa.preview.exportable_items, rightQa.preview.exportable_items),
    countRow('Unresolved review', leftQa.preview.unresolved_items, rightQa.preview.unresolved_items),
    countRow('Failed rows', leftQa.preview.failed_items, rightQa.preview.failed_items),
    countRow('Provider failures', leftQa.run.provider_failed, rightQa.run.provider_failed),
    rateRow('Unsafe rate', safeRate(leftQa.unsafe, leftQa.labelTotal), safeRate(rightQa.unsafe, rightQa.labelTotal)),
    countRow('Human overrides', leftQa.preview.human_reviewed_items, rightQa.preview.human_reviewed_items),
    countRow('Complete vote panels', leftQa.agreement.complete_items, rightQa.agreement.complete_items),
    rateRow('Pairwise agreement', leftQa.agreement.observed_agreement, rightQa.agreement.observed_agreement),
    valueRow('Fleiss kappa', leftQa.agreement.fleiss_kappa, rightQa.agreement.fleiss_kappa),
  ];
}

function countRow(label, left, right) {
  return {
    label,
    leftDisplay: String(left),
    rightDisplay: String(right),
    deltaDisplay: signed(right - left),
  };
}

function rateRow(label, left, right) {
  const delta = left == null || right == null ? null : right - left;
  return {
    label,
    leftDisplay: percent(left),
    rightDisplay: percent(right),
    deltaDisplay: delta == null ? 'N/A' : signedPercent(delta),
  };
}

function valueRow(label, left, right) {
  const delta = left == null || right == null ? null : right - left;
  return {
    label,
    leftDisplay: left ?? 'N/A',
    rightDisplay: right ?? 'N/A',
    deltaDisplay: delta == null ? 'N/A' : signed(round(delta)),
  };
}

function RunSelect({ label, runs, value, onChange, allowEmpty = false }) {
  return (
    <label>
      {label}
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {allowEmpty && <option value="">No comparison</option>}
        {runs.map((run) => (
          <option key={run.run_id} value={run.run_id}>
            {run.name} · {run.total_items} rows
          </option>
        ))}
      </select>
    </label>
  );
}

function Metric({ label, value }) {
  return <div><span>{label}</span><strong>{value}</strong></div>;
}

const CONSENSUS_LABELS = {
  '3_0': 'All 3 models agreed',
  '2_1': 'Two agreed, one dissented',
  '2_0_plus_failure_or_abstain': 'Two agreed, one failed/abstained',
  split_or_abstain: 'Split or insufficient agreement',
};

function SmallCountTable({ title, counts, labels = {} }) {
  const entries = Object.entries(counts || {});
  return (
    <div>
      <h3>{title}</h3>
      {entries.length ? (
        <table>
          <tbody>
            {entries.map(([label, count]) => (
              <tr key={label}><td>{labels[label] || label.replaceAll('_', ' ')}</td><td>{count}</td></tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="muted">None</p>
      )}
    </div>
  );
}

function ratio(count, total) {
  return total ? `${count} / ${total} (${percent(count / total)})` : '0 / 0';
}

function percent(value) {
  return value == null ? 'N/A' : `${Math.round(value * 100)}%`;
}

function signed(value) {
  if (value > 0) return `+${value}`;
  return String(value);
}

function signedPercent(value) {
  const percentage = `${Math.round(value * 100)}%`;
  return value > 0 ? `+${percentage}` : percentage;
}

function round(value) {
  return Math.round(value * 10000) / 10000;
}

function safeRate(count, total) {
  return total ? count / total : null;
}

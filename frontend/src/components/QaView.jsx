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
              <Metric label="Safe labels" value={ratio(leftQa.safe, leftQa.labelTotal)} />
              <Metric label="Unsafe labels" value={ratio(leftQa.unsafe, leftQa.labelTotal)} />
              <Metric label="Unsafe rate" value={percent(leftQa.labelTotal ? leftQa.unsafe / leftQa.labelTotal : null)} />
              <Metric label="Human overrides" value={ratio(leftQa.preview.human_reviewed_items, leftQa.preview.total_items)} />
              <Metric label="Complete panels" value={ratio(leftQa.agreement.complete_items, leftQa.preview.total_items)} />
            </div>
          </div>
        )}
      </section>

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
    const [run, preview, agreement, labels] = await Promise.all([
      api.getRun(runId),
      api.exportPreview(runId),
      api.runAgreement(runId),
      api.exportRunLabels(runId, false),
    ]);
    const safe = labels.filter((label) => label.label === 'safe').length;
    const unsafe = labels.filter((label) => label.label === 'unsafe').length;
    const unresolved = labels.filter((label) => label.label === 'needs_human_review').length;
    setQa({ run, preview, agreement, labels, safe, unsafe, unresolved, labelTotal: labels.length });
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
    countRow('Safe labels', leftQa.safe, rightQa.safe),
    countRow('Unsafe labels', leftQa.unsafe, rightQa.unsafe),
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

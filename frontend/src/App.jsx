import { useEffect, useState } from 'react';
import { api } from './api';
import AnnotateView from './components/AnnotateView';
import ReviewView from './components/ReviewView';
import ResultsView from './components/ResultsView';
import './App.css';

const VIEWS = [
  ['annotate', 'Annotate'],
  ['review', 'Review'],
  ['results', 'Results'],
];

export default function App() {
  const [view, setView] = useState('annotate');
  const [health, setHealth] = useState(null);
  const [reviewCount, setReviewCount] = useState(0);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [selectedRunId, setSelectedRunId] = useState(null);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
    if (!selectedRunId) {
      setReviewCount(0);
      return;
    }
    api.runReviewQueue(selectedRunId).then((queue) => setReviewCount(queue.length)).catch(() => setReviewCount(0));
  }, [refreshVersion, selectedRunId]);

  function dataChanged() {
    setRefreshVersion((value) => value + 1);
  }

  return (
    <main className="app">
      <header className="topbar">
        <div>
          <h1>Cyber Annotation Council</h1>
          <p>Three independent AI annotations with deterministic decisions and human review.</p>
        </div>
        <div className={`service-status ${health?.status === 'ok' ? 'ready' : ''}`}>
          {health?.status === 'ok' ? 'Internal models available' : 'Service unavailable'}
        </div>
      </header>

      <nav className="view-tabs" aria-label="Annotation workflow">
        {VIEWS.map(([id, label]) => (
          <button
            key={id}
            type="button"
            className={view === id ? 'view-tab active' : 'view-tab'}
            onClick={() => setView(id)}
          >
            {label}
            {id === 'review' && reviewCount > 0 && <span className="count-badge">{reviewCount}</span>}
          </button>
        ))}
      </nav>

      {view === 'annotate' && (
        <AnnotateView
          onComplete={(response) => {
            if (response?.run?.run_id) setSelectedRunId(response.run.run_id);
            dataChanged();
            setView('results');
          }}
        />
      )}
      {view === 'review' && (
        <ReviewView
          refreshVersion={refreshVersion}
          selectedRunId={selectedRunId}
          onSaved={dataChanged}
        />
      )}
      {view === 'results' && (
        <ResultsView
          refreshVersion={refreshVersion}
          selectedRunId={selectedRunId}
          onRunSelected={setSelectedRunId}
          onReview={() => setView('review')}
          onDataChanged={dataChanged}
        />
      )}
    </main>
  );
}

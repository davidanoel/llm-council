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

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
    api.reviewQueue().then((queue) => setReviewCount(queue.length)).catch(() => setReviewCount(0));
  }, [refreshVersion]);

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
          onComplete={() => {
            dataChanged();
            setView('results');
          }}
        />
      )}
      {view === 'review' && <ReviewView refreshVersion={refreshVersion} onSaved={dataChanged} />}
      {view === 'results' && <ResultsView refreshVersion={refreshVersion} onReview={() => setView('review')} />}
    </main>
  );
}

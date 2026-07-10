import { useState } from 'react';
import { Route, Routes } from 'react-router-dom';
import RecordOverlay from './components/RecordOverlay';
import StatsPage from './pages/StatsPage';

// New pages get added here as extra <Route> entries; the Record FAB lives
// outside the router so it stays visible on every page.
export default function App() {
  const [recordOpen, setRecordOpen] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  const onSaved = () => setRefreshKey((k) => k + 1);

  return (
    <>
      <header className="app-header">
        <h1>📈 Market Prep</h1>
        <span className="date">
          {new Date().toLocaleDateString('en-GB', {
            weekday: 'short', day: '2-digit', month: 'short', year: 'numeric',
            timeZone: 'UTC',
          })}{' '}
          UTC
        </span>
      </header>

      <Routes>
        <Route path="*" element={<StatsPage refreshKey={refreshKey} />} />
      </Routes>

      <button className="fab" aria-label="Record" onClick={() => setRecordOpen(true)}>
        +
      </button>
      {recordOpen && (
        <RecordOverlay onClose={() => setRecordOpen(false)} onSaved={onSaved} />
      )}
    </>
  );
}

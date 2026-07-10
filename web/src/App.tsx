import { useState } from 'react';
import { NavLink, Route, Routes } from 'react-router-dom';
import RecordOverlay from './components/RecordOverlay';
import HistoryPage from './pages/HistoryPage';
import MarketPrepPage from './pages/MarketPrepPage';

// New pages: add a <Route> plus a nav link. The Record FAB lives outside
// the router so it stays visible on every page.
export default function App() {
  const [recordOpen, setRecordOpen] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  const onSaved = () => setRefreshKey((k) => k + 1);

  return (
    <>
      <header className="app-header">
        <h1>📈 Market Prep</h1>
        <nav className="main-nav">
          <NavLink to="/" end>Market Prep</NavLink>
          <NavLink to="/history">History</NavLink>
        </nav>
        <span className="date">
          {new Date().toLocaleDateString('en-GB', {
            weekday: 'short', day: '2-digit', month: 'short', year: 'numeric',
            timeZone: 'UTC',
          })}{' '}
          UTC
        </span>
      </header>

      <Routes>
        <Route path="/history" element={<HistoryPage />} />
        <Route path="*" element={<MarketPrepPage refreshKey={refreshKey} />} />
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

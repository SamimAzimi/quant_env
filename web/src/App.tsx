import { useState } from 'react';
import { NavLink, Route, Routes } from 'react-router-dom';
import AlertBell from './components/AlertBell';
import RecordOverlay from './components/RecordOverlay';
import AssetStatsPage from './pages/AssetStatsPage';
import HistoryPage from './pages/HistoryPage';
import MarketPrepPage from './pages/MarketPrepPage';

// New pages: add a <Route> plus a nav link (and one in the mobile menu).
// The Record FAB and nav FAB live outside the router so they stay visible
// on every page.
export default function App() {
  const [recordOpen, setRecordOpen] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  const onSaved = () => setRefreshKey((k) => k + 1);

  return (
    <>
      <header className="app-header">
        <h1>📈 Market Prep</h1>
        <nav className="main-nav">
          <NavLink to="/" end>Market Prep</NavLink>
          <NavLink to="/history">History</NavLink>
          <NavLink to="/asset-stats">Asset Stats</NavLink>
        </nav>
        <span className="date" title={`frontend built ${__BUILD_TIME__} UTC`}>
          {new Date().toLocaleDateString('en-GB', {
            weekday: 'short', day: '2-digit', month: 'short', year: 'numeric',
            timeZone: 'UTC',
          })}{' '}
          UTC
          <span className="muted" style={{ marginLeft: 8, fontSize: 11 }}>
            build {__BUILD_TIME__}
          </span>
        </span>
        <AlertBell refreshKey={refreshKey} />
      </header>

      <Routes>
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/asset-stats" element={<AssetStatsPage />} />
        <Route path="*" element={<MarketPrepPage refreshKey={refreshKey} />} />
      </Routes>

      <button className="fab nav-fab" aria-label="Menu" onClick={() => setNavOpen((v) => !v)}>
        ☰
      </button>
      {navOpen && (
        <div className="nav-menu" onClick={() => setNavOpen(false)}>
          <NavLink to="/" end>Market Prep</NavLink>
          <NavLink to="/history">History</NavLink>
          <NavLink to="/asset-stats">Asset Stats</NavLink>
        </div>
      )}

      <button className="fab" aria-label="Record" onClick={() => setRecordOpen(true)}>
        +
      </button>
      {recordOpen && (
        <RecordOverlay onClose={() => setRecordOpen(false)} onSaved={onSaved} />
      )}
    </>
  );
}

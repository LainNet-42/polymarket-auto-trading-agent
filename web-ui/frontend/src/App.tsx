import { useState, useEffect } from 'react';
import Navbar from './components/common/Navbar';
import Live from './pages/Live';
import TradingLog from './pages/TradingLog';
import Trace from './pages/Trace';

export type Page = 'live' | 'tradinglog' | 'trace';

function getPageFromHash(): Page {
  const hash = window.location.hash.replace('#/', '');
  if (hash === 'trading-log') return 'tradinglog';
  if (hash === 'trace') return 'trace';
  return 'live';
}

function App() {
  const [page, setPage] = useState<Page>(getPageFromHash);

  useEffect(() => {
    const handler = () => setPage(getPageFromHash());
    window.addEventListener('hashchange', handler);
    return () => window.removeEventListener('hashchange', handler);
  }, []);

  return (
    <div className="app">
      <Navbar currentPage={page} />
      <main className="main-content">
        {page === 'live' && <Live />}
        {page === 'tradinglog' && <TradingLog />}
        {page === 'trace' && <Trace />}
      </main>
    </div>
  );
}

export default App;

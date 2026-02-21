import { usePolling } from '../hooks/usePolling';
import { fetchTradingLog, TradingLogEntry } from '../services/api';
import dayjs from 'dayjs';
import './TradingLog.css';

const TradingLog = () => {
  const { data: tradingLog, loading } = usePolling<TradingLogEntry[]>({
    fetcher: fetchTradingLog,
    interval: 30000,
  });

  const MAX_RECENT = 50;

  const entries = tradingLog
    ? [...tradingLog].sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime())
        .slice(0, MAX_RECENT)
    : [];

  const formatTime = (ts: string) => {
    if (!ts) return '';
    return dayjs(ts).format('YYYY-MM-DD HH:mm');
  };

  return (
    <div className="tradinglog-container">
      <div className="tradinglog-header">
        <h2>TRADING LOG (AGENT MEMORY)</h2>
        <span className="tradinglog-count">Last {entries.length} entries</span>
      </div>
      <div className="tradinglog-table-wrapper">
        {loading ? (
          <div className="tradinglog-loading">Loading...</div>
        ) : (
          <table className="tradinglog-table">
            <thead>
              <tr>
                <th className="th-num">#</th>
                <th className="th-date">DATE</th>
                <th className="th-decision">DECISION</th>
                <th className="th-why">WHY</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry, i) => (
                <tr
                  key={i}
                  className={
                    entry.decision.startsWith('BUY') ? 'row-buy' :
                    entry.decision.startsWith('SELL') ? 'row-sell' :
                    entry.decision === 'HOLD' ? 'row-hold' :
                    entry.decision === 'INIT' ? 'row-init' : ''
                  }
                >
                  <td className="col-num">{entry.invoke_num}</td>
                  <td className="col-date">{formatTime(entry.date)}</td>
                  <td className="col-decision">{entry.decision || '--'}</td>
                  <td className="col-why">{entry.why || '--'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};

export default TradingLog;

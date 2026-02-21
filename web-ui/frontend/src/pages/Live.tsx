import { useState, useMemo, useEffect, useRef } from 'react';
import AccountValueChart from '../components/trading/AccountValueChart';
import { usePolling } from '../hooks/usePolling';
import { useRealtimeStatus } from '../hooks/useWebSocket';
import {
  fetchStatus,
  fetchPortfolioHistory,
  fetchTradingLog,
  fetchTrades,
  fetchMarketImage,
  fetchHibernate,
  fetchConfig,
  StatusData,
  PortfolioPoint,
  TradingLogEntry,
  TradeEntry,
  HibernateData,
  ConfigData,
} from '../services/api';
import dayjs from 'dayjs';
import './Live.css';

const INITIAL_DEPOSIT = parseFloat(import.meta.env.VITE_INITIAL_DEPOSIT || '100');

const Live = () => {
  const [selectedTab, setSelectedTab] = useState<'phone' | 'trades' | 'decisions'>('phone');
  const [phoneModal, setPhoneModal] = useState(false);
  const [chartTimeRange, setChartTimeRange] = useState<'all' | '72h'>('all');
  const [liveStatus, setLiveStatus] = useState<StatusData | null>(null);
  const [positionImages, setPositionImages] = useState<Record<string, string>>({});

  // Polling for initial data + fallback
  const { data: polledStatus } = usePolling<StatusData>({ fetcher: fetchStatus, interval: 30000 });
  const { data: history } = usePolling<PortfolioPoint[]>({ fetcher: fetchPortfolioHistory, interval: 30000 });
  const { data: tradingLog } = usePolling<TradingLogEntry[]>({ fetcher: fetchTradingLog, interval: 30000 });
  const { data: trades } = usePolling<TradeEntry[]>({ fetcher: fetchTrades, interval: 30000 });

  // WebSocket for real-time price updates
  const { connected } = useRealtimeStatus({
    onMessage: (data) => {
      if (data.type === 'price_update') {
        setLiveStatus(data);
      }
    },
  });

  // Use WebSocket data if available, fallback to polled
  const status = liveStatus || polledStatus;

  const totalValue = status?.total_value ?? 0;
  const balance = status?.balance_usdc ?? 0;
  const positionsValue = status?.positions_value ?? 0;
  const numPositions = status?.num_positions ?? 0;
  const pnl = totalValue - INITIAL_DEPOSIT;
  const pnlPct = INITIAL_DEPOSIT > 0 ? (pnl / INITIAL_DEPOSIT) * 100 : 0;

  // UTC flip clock
  const [utcTime, setUtcTime] = useState(() => {
    const now = new Date();
    return {
      h: String(now.getUTCHours()).padStart(2, '0'),
      m: String(now.getUTCMinutes()).padStart(2, '0'),
      s: String(now.getUTCSeconds()).padStart(2, '0'),
    };
  });
  const prevTimeRef = useRef(utcTime);

  useEffect(() => {
    const tick = () => {
      const now = new Date();
      const next = {
        h: String(now.getUTCHours()).padStart(2, '0'),
        m: String(now.getUTCMinutes()).padStart(2, '0'),
        s: String(now.getUTCSeconds()).padStart(2, '0'),
      };
      prevTimeRef.current = utcTime;
      setUtcTime(next);
    };
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [utcTime]);

  // Hibernate polling
  const { data: hibernate } = usePolling<HibernateData>({ fetcher: fetchHibernate, interval: 30000 });

  // Config (rarely changes, poll slowly)
  const { data: config } = usePolling<ConfigData>({ fetcher: fetchConfig, interval: 120000 });

  // Compute countdown if hibernating
  const hibernateCountdown = useMemo(() => {
    if (!hibernate?.hibernating || !hibernate.wake_time) return null;
    try {
      const wake = new Date(hibernate.wake_time).getTime();
      const now = Date.now();
      const diff = wake - now;
      if (diff <= 0) return null;
      const h = String(Math.floor(diff / 3600000)).padStart(2, '0');
      const m = String(Math.floor((diff % 3600000) / 60000)).padStart(2, '0');
      const s = String(Math.floor((diff % 60000) / 1000)).padStart(2, '0');
      return { h, m, s };
    } catch {
      return null;
    }
  }, [hibernate, utcTime]); // re-compute every second via utcTime dep

  // D-Mail highlight helper: colorize $amounts, SKIP, market slugs
  const highlightDMail = (text: string) => {
    if (!text) return '';
    return text
      .replace(/(\$[\d,.]+)/g, '<span class="dmail-amount">$1</span>')
      .replace(/\b(SKIP|SKIPPED)\b/g, '<span class="dmail-skip">$1</span>')
      .replace(/\b(CHECK|WAIT|Priority)\b/g, '<span class="dmail-action">$1</span>');
  };

  // Fetch position images when positions change
  useEffect(() => {
    if (!status?.positions) return;
    status.positions.forEach((pos) => {
      const slug = pos.event_slug || '';
      if (slug && positionImages[slug] === undefined) {
        fetchMarketImage(slug).then((url) => {
          if (url) {
            setPositionImages((prev) => ({ ...prev, [slug]: url }));
          }
        });
      }
    });
  }, [status?.positions]);

  // Filter chart data by time range
  const chartData = useMemo(() => {
    if (!history || history.length === 0) return [];
    if (chartTimeRange === 'all') return history;
    const cutoff = dayjs().subtract(72, 'hour');
    return history.filter((p) => dayjs(p.timestamp).isAfter(cutoff));
  }, [history, chartTimeRange]);

  const formatTime = (ts: string) => {
    if (!ts) return '';
    return dayjs(ts).format('MM/DD HH:mm');
  };

  const formatSlug = (slug: string) => {
    if (!slug) return '';
    return slug;
  };

  const MAX_RECENT = 50;

  // Sort trades newest first, cap at 50
  const sortedTrades = trades ? [...trades].sort((a, b) =>
    new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
  ).slice(0, MAX_RECENT) : [];

  // Sort decisions newest first, skip INIT and empty, cap at 50
  const sortedDecisions = tradingLog
    ? [...tradingLog]
        .filter((d) => d.decision !== 'INIT' && d.decision !== '')
        .sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime())
        .slice(0, MAX_RECENT)
    : [];

  return (
    <div className="live-container">
      {/* Top Status Bar */}
      <div className="top-status-bar">
        <div className="status-bar-content">
          <div className="crypto-prices">
            <div className="price-item">
              <div className="price-header">
                <span className="crypto-symbol">CASH REMAINING</span>
              </div>
              <div className="price-value">${balance.toFixed(2)}</div>
            </div>
            <div className="price-item">
              <div className="price-header">
                <span className="crypto-symbol">NOTIONAL VALUE</span>
              </div>
              <div className="price-value">${totalValue.toFixed(2)}</div>
            </div>
            <div className="price-item pnl-item">
              <div className="price-header">
                <span className="crypto-symbol">P&L</span>
              </div>
              <div className={`price-value ${pnl >= 0 ? 'terminal-positive' : 'terminal-negative'}`}>
                {pnl >= 0 ? '+' : ''}${pnl.toFixed(2)} ({pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(1)}%)
              </div>
            </div>
          </div>
          <div className="flip-clock">
            {[utcTime.h, utcTime.m, utcTime.s].map((val, gi) => (
              <span key={gi} className="flip-group">
                {gi > 0 && <span className="flip-colon">:</span>}
                {val.split('').map((digit, di) => {
                  const prev = [prevTimeRef.current.h, prevTimeRef.current.m, prevTimeRef.current.s][gi];
                  const prevDigit = prev[di] || '0';
                  const changed = digit !== prevDigit;
                  return (
                    <span key={`u${gi}-${di}`} className="flip-digit-wrapper">
                      <span className={`flip-digit ${changed ? 'flip' : ''}`}>{digit}</span>
                    </span>
                  );
                })}
              </span>
            ))}
            <span className="flip-label">UTC</span>
          </div>
        </div>
      </div>

      {/* Main Content Area */}
      <div className="live-main-content">
        {/* Left Section */}
        <div className="left-section">
          {/* Chart Area */}
          <div className="chart-area">
            <div className="chart-header">
              <h2>TOTAL ACCOUNT VALUE <span className="chart-change" style={{ fontSize: '14px', fontWeight: 400 }}>({pnl >= 0 ? '+' : ''}${pnl.toFixed(2)})</span></h2>
              <div className="chart-time-selector">
                <button
                  className={`time-btn ${chartTimeRange === 'all' ? 'active' : ''}`}
                  onClick={() => setChartTimeRange('all')}
                >
                  ALL
                </button>
                <button
                  className={`time-btn ${chartTimeRange === '72h' ? 'active' : ''}`}
                  onClick={() => setChartTimeRange('72h')}
                >
                  72H
                </button>
              </div>
            </div>
            <div className="chart-container">
              <AccountValueChart data={chartData} />
            </div>
          </div>

          {/* Summary Cards */}
          <div className="model-cards-section">
            <div className="model-cards-grid">
              <div className="model-card-mini positions-summary-card">
                <div className="model-card-header">
                  <span className="model-name">POSITIONS</span>
                </div>
                <div className="model-card-balance">{numPositions}</div>
                <div className="positions-summary-value">${positionsValue.toFixed(2)}</div>
              </div>
              {(status?.positions || []).map((pos, i) => {
                const posPnl = pos.pnl ?? 0;
                const slug = pos.event_slug || '';
                const imageUrl = positionImages[slug] || '';
                const polymarketUrl = slug ? `https://polymarket.com/event/${slug}` : '';
                return (
                  <a
                    key={i}
                    className="model-card-mini position-link"
                    href={polymarketUrl || undefined}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ textDecoration: 'none', color: 'inherit' }}
                  >
                    {imageUrl && (
                      <img src={imageUrl} alt="" className="position-image" />
                    )}
                    <div className="model-card-header">
                      <span className="model-name">{pos.outcome} @ {formatSlug(slug)}</span>
                    </div>
                    <div className="model-card-balance">${(pos.current_value ?? 0).toFixed(2)}</div>
                    <div className={`model-card-pnl ${posPnl >= 0 ? 'positive' : 'negative'}`}>
                      {posPnl >= 0 ? '+' : ''}{posPnl.toFixed(2)}
                    </div>
                  </a>
                );
              })}
            </div>
          </div>
        </div>

        {/* Right Section */}
        <div className="right-section">
          {/* Tabs */}
          <div className="trade-tabs">
            <button
              className={`trade-tab ${selectedTab === 'phone' ? 'active' : ''}`}
              onClick={() => setSelectedTab('phone')}
            >
              PHONE
            </button>
            <button
              className={`trade-tab ${selectedTab === 'trades' ? 'active' : ''}`}
              onClick={() => setSelectedTab('trades')}
            >
              TRADES
            </button>
            <button
              className={`trade-tab ${selectedTab === 'decisions' ? 'active' : ''}`}
              onClick={() => setSelectedTab('decisions')}
            >
              DECISIONS
            </button>
          </div>

          {/* Filter Bar */}
          <div className="filter-bar">
            <div className="filter-controls">
              <span className="filter-label">
                {selectedTab === 'phone' ? 'D-MAIL' : selectedTab === 'trades' ? 'RECENT TRADE HISTORY' : 'RECENT DECISIONS'}
              </span>
            </div>
            <span className="trade-count">
              {selectedTab === 'phone'
                ? 'Last message from agent'
                : selectedTab === 'trades'
                  ? `Last ${sortedTrades.length} trades`
                  : `Last ${sortedDecisions.length} decisions`}
            </span>
          </div>

          {/* Content */}
          <div className="trade-list">
            {selectedTab === 'phone' && (
              <div className="dmail-phone-panel">
                {hibernateCountdown && (
                  <div className="dmail-note-clock">
                    <div className="flip-clock flip-clock-bw">
                      {[hibernateCountdown.h, hibernateCountdown.m, hibernateCountdown.s].map((val, gi) => (
                        <span key={gi} className="flip-group">
                          {gi > 0 && <span className="flip-colon">:</span>}
                          {val.split('').map((digit, di) => (
                            <span key={`${gi}-${di}`} className="flip-digit-wrapper">
                              <span className="flip-digit">{digit}</span>
                            </span>
                          ))}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                <div className="dmail-phone-container" onClick={() => setPhoneModal(true)}>
                  <img src="/phone.png" alt="" className="dmail-phone-img" />
                  <div className="dmail-screen">
                    {hibernate?.d_mail ? (
                      <>
                        <div className="dmail-navbar">
                          <span className="dmail-nav-left">Back</span>
                          <span className="dmail-nav-right">Receive mail</span>
                        </div>
                        <div className="dmail-meta">
                          <div className="dmail-meta-row">
                            <span className="dmail-meta-sender">Agent</span>
                            <span className="dmail-meta-time">{hibernate.timestamp ? dayjs(hibernate.timestamp).format('M/D HH:mm') : ''}</span>
                          </div>
                          <div className="dmail-meta-row">
                            <span className="dmail-meta-subject">D-Mail #{hibernate.invoke_num}</span>
                          </div>
                        </div>
                        <div className="dmail-body">
                          <div className="dmail-hibernate-line">Hibernate {hibernate.hours ?? 0}h</div>
                          <div dangerouslySetInnerHTML={{ __html: highlightDMail(hibernate.d_mail) }} />
                        </div>
                      </>
                    ) : (
                      <div className="dmail-empty">NO D-MAIL</div>
                    )}
                  </div>
                </div>
                <div className="dmail-notes">
                  {config && (() => {
                    const enabled = config.hibernate.find((p) => p.key === 'HIBERNATE_ENABLED');
                    const maxH = config.hibernate.find((p) => p.key === 'MAX_HIBERNATE_HOURS');
                    const defaultH = config.hibernate.find((p) => p.key === 'DEFAULT_WAKE_INTERVAL');
                    const isOn = enabled?.value === true;
                    const maxVal = typeof maxH?.value === 'number' ? maxH.value : 24;
                    const defaultVal = typeof defaultH?.value === 'number' ? defaultH.value : 4;
                    const minVal = 0.5;
                    const pct = ((defaultVal - minVal) / (maxVal - minVal)) * 100;
                    return (
                      <div className="dmail-note-block">
                        <div className="dmail-note-header">
                          <span className="dmail-note-term">Hibernate</span>
                          <div className="config-toggle">
                            <span className={`toggle-option ${isOn ? 'toggle-on' : 'toggle-off-label'}`}>ON</span>
                            <span className={`toggle-option ${!isOn ? 'toggle-off' : 'toggle-on-label'}`}>OFF</span>
                          </div>
                        </div>
                        <div className="dmail-note-desc">Tokens are expensive. To avoid wasting resources and learn from its lesson, the agent will set <span className="term-hibernate">Hibernate time</span> & <span className="term-dmail">D-mail</span> after each run.</div>
                        <div className="note-divider" />
                        <div className="note-children">
                          <div className="note-child">
                            <div className="config-key term-hibernate">Hibernate time range</div>
                            <div className="config-slider">
                              <span className="slider-label-min">{minVal}h</span>
                              <div className="slider-track">
                                <div className="slider-fill" style={{ width: `${pct}%` }} />
                                <div className="slider-thumb" style={{ left: `${pct}%` }} />
                              </div>
                              <span className="slider-label-max">{maxVal}h</span>
                            </div>
                            <div className="slider-default">Default: {defaultVal}h</div>
                            <div className="config-desc">Sleep duration before the agent wakes for its next run.</div>
                          </div>
                          <div className="note-child-divider" />
                          <div className="note-child">
                            <div className="dmail-note-term term-dmail">D-Mail</div>
                            <div className="dmail-note-desc">Like in <a href="https://steins-gate.fandom.com/wiki/D-Mail" target="_blank" rel="noopener noreferrer" className="steinsgate-link">Steins;Gate</a>, D-Mail is a message sent to guide its future self to finish what hasn't been done yet, altering the world line.</div>
                          </div>
                        </div>
                      </div>
                    );
                  })()}
                </div>
                {config && (
                  <div className="config-panel-box">
                    <div className="config-panel-bar">
                      <span className="config-panel-bar-label">RISK MANAGEMENT</span>
                      <span className="config-panel-bar-sub">Config</span>
                    </div>
                    <div className="config-panel-body">
                      {config.risk.map((p) => (
                        <div key={p.key} className="config-row">
                          <div className="config-key">{p.key}</div>
                          <div className="config-val">{typeof p.value === 'number' && p.value < 1 ? `${(p.value * 100).toFixed(0)}%` : String(p.value)}</div>
                          <div className="config-desc">{p.desc}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
            {selectedTab === 'trades' && (
              sortedTrades.length === 0 ? (
                <div className="no-data-message">No trades yet</div>
              ) : (
                sortedTrades.map((trade, i) => {
                  return (
                    <div key={i} className="trade-item">
                      <div className="trade-header">
                        <div className="trade-info">
                          <span className="trade-side">
                            {trade.side}
                          </span>
                          <span> </span>
                          <span className="outcome-bubble">{trade.size} {trade.outcome}</span>
                          <span> @ ${(trade.price ?? 0).toFixed(3)}</span>
                        </div>
                        <span className="trade-time">{formatTime(trade.timestamp)}</span>
                      </div>
                      <div className="trade-details">
                        <div className="trade-detail-row">
                          {formatSlug(trade.event_slug)}
                        </div>
                        {trade.side === 'STOP_LOSS' ? (
                          <div className="trade-detail-row terminal-negative">
                            -{((trade.size ?? 0) * ((trade as any).entry_price - trade.price)).toFixed(2)} (sold @ ${(trade.price ?? 0).toFixed(3)}, entry @ ${((trade as any).entry_price ?? 0).toFixed(3)}, drop {(trade as any).drop_pct}%)
                          </div>
                        ) : (
                          <div className={`trade-detail-row ${trade.side === 'BUY' ? 'terminal-negative' : 'terminal-positive'}`}>
                            {trade.side === 'BUY' ? '-' : '+'}${((trade.size ?? 0) * (trade.price ?? 0)).toFixed(2)}
                          </div>
                        )}
                        {trade.pnl !== undefined && trade.pnl !== null && trade.pnl !== 0 && (
                          <div className="trade-pnl">
                            <span className="pnl-label">P&L:</span>
                            <span className={`pnl-value ${trade.pnl >= 0 ? 'profit' : 'loss'}`}>
                              {(trade.pnl ?? 0) >= 0 ? '+' : ''}${(trade.pnl ?? 0).toFixed(2)}
                            </span>
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })
              )
            )}

            {selectedTab === 'decisions' && (
              sortedDecisions.length === 0 ? (
                <div className="no-data-message">No decisions yet</div>
              ) : (
                sortedDecisions.map((d, i) => (
                  <div key={i} className="trade-item">
                    <div className="trade-header">
                      <div className="trade-info">
                        <span className="model-name-inline">#{d.invoke_num}</span>
                        <span> </span>
                        <span className={`trade-side ${
                          d.decision.startsWith('BUY') ? 'buy' :
                          d.decision.startsWith('SELL') ? 'sell' :
                          d.decision === 'HOLD' ? 'hold' : ''
                        }`}>
                          {d.decision}
                        </span>
                      </div>
                      <span className="trade-time">{formatTime(d.date)}</span>
                    </div>
                    <div className="trade-details">
                      <div className="trade-detail-row" style={{ color: '#666' }}>
                        {d.why}
                      </div>
                    </div>
                  </div>
                ))
              )
            )}


          </div>
        </div>
      </div>

      {/* Phone Fullscreen Modal */}
      {phoneModal && (
        <div className="phone-modal-overlay" onClick={() => setPhoneModal(false)}>
          <div className="phone-modal" onClick={(e) => e.stopPropagation()}>
            <button className="phone-modal-close" onClick={() => setPhoneModal(false)}>X</button>
            <div className="phone-modal-layout">
              <div className="phone-modal-phone">
                <img src="/phone.png" alt="" className="dmail-phone-img" />
                <div className="dmail-screen dmail-screen-lg">
                  {hibernate?.d_mail ? (
                    <>
                      <div className="dmail-navbar dmail-navbar-lg">
                        <span className="dmail-nav-left">Back</span>
                        <span className="dmail-nav-right">Receive mail</span>
                      </div>
                      <div className="dmail-meta dmail-meta-lg">
                        <div className="dmail-meta-row">
                          <span className="dmail-date">{hibernate.timestamp ? dayjs(hibernate.timestamp).format('M/D HH:mm') : ''}</span>
                        </div>
                        <div className="dmail-meta-row">
                          <span className="dmail-from">Agent</span>
                        </div>
                        <div className="dmail-meta-row">
                          <span className="dmail-subject">D-Mail #{hibernate.invoke_num}</span>
                        </div>
                      </div>
                      <div className="dmail-body dmail-body-lg" dangerouslySetInnerHTML={{ __html: highlightDMail(hibernate.d_mail) }} />
                    </>
                  ) : (
                    <div className="dmail-empty">NO D-MAIL</div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default Live;

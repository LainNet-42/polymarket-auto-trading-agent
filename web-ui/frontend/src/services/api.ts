import axios from 'axios';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '/api',
  timeout: 10000,
});

export interface StatusData {
  balance_usdc: number;
  positions_value: number;
  total_value: number;
  num_positions: number;
  last_updated: string;
  positions: Position[];
}

export interface Position {
  market_slug: string;
  outcome: string;
  shares: number;
  entry_price: number;
  avg_price: number;
  current_value: number;
  token_id: string;
  pnl?: number;
  end_date?: string;
  event_slug?: string;
  redeemable?: boolean;
}

export interface PortfolioPoint {
  timestamp: string;
  balance?: number;
  positions_value?: number;
  total_value: number;
}

export interface TradingLogEntry {
  invoke_num: string;
  date: string;
  decision: string;
  why: string;
}

export interface TradeEntry {
  timestamp: string;
  side: string;
  size: number;
  price: number;
  event_slug: string;
  outcome: string;
  pnl?: number;
}

export interface TraceSummary {
  invoke_num: number;
  date: string;
  file: string;
  message_count: number;
}

export interface TraceMessage {
  role: string;
  content: string;
  tool_name?: string;
  tool_input?: string;
  tool_result?: string;
}

export async function fetchStatus(): Promise<StatusData> {
  const { data } = await api.get('/status');
  return data;
}

export async function fetchPortfolioHistory(): Promise<PortfolioPoint[]> {
  const { data } = await api.get('/portfolio-history');
  return data;
}

export async function fetchTradingLog(): Promise<TradingLogEntry[]> {
  const { data } = await api.get('/trading-log');
  return data;
}

export async function fetchTrades(): Promise<TradeEntry[]> {
  const { data } = await api.get('/trades');
  return data;
}

export async function fetchTraceList(): Promise<TraceSummary[]> {
  const { data } = await api.get('/trace/list');
  return data;
}

export async function fetchTrace(invokeNum: number): Promise<TraceMessage[]> {
  const { data } = await api.get(`/trace/${invokeNum}`);
  return data;
}

export async function fetchWallet(): Promise<{ address: string }> {
  const { data } = await api.get('/wallet');
  return data;
}

export interface HibernateData {
  hibernating: boolean;
  wake_time: string | null;
  invoke_num: number | null;
  hours: number | null;
  d_mail: string | null;
  timestamp: string | null;
  source: string | null;
}

export async function fetchHibernate(): Promise<HibernateData> {
  const { data } = await api.get('/hibernate');
  return data;
}

export interface ConfigParam {
  key: string;
  value: number | boolean;
  desc: string;
}

export interface ConfigData {
  risk: ConfigParam[];
  hibernate: ConfigParam[];
}

export async function fetchConfig(): Promise<ConfigData> {
  const { data } = await api.get('/config');
  return data;
}

const _imageCache: Record<string, string> = {};

export async function fetchMarketImage(slug: string): Promise<string> {
  if (_imageCache[slug] !== undefined) return _imageCache[slug];
  try {
    const { data } = await api.get(`/market-image/${slug}`);
    _imageCache[slug] = data.image || '';
    return _imageCache[slug];
  } catch {
    _imageCache[slug] = '';
    return '';
  }
}

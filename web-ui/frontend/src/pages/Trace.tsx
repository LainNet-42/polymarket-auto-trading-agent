import { useState, useEffect, useRef } from 'react';
import { fetchTraceList, TraceSummary } from '../services/api';
import { usePolling } from '../hooks/usePolling';
import dayjs from 'dayjs';
import axios from 'axios';
import './Trace.css';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '/api',
  timeout: 30000,
});

// ---------- Types ----------

interface RawTraceMsg {
  timestamp: string;
  invoke_num: number;
  msg_type: string;
  content?: Array<{
    type: string;
    text?: string;
    name?: string;
    id?: string;
    input?: any;
    tool_use_id?: string;
    content?: string;
    is_error?: boolean;
  }>;
  result?: string;
}

type TraceItem =
  | { kind: 'system' }
  | { kind: 'agent'; text: string }
  | { kind: 'tool'; name: string; args: string; result: string; isError: boolean }
  | { kind: 'result'; text: string };

// ---------- Error detection ----------

const ERROR_PATTERNS = /\b(error|failed|not found|exception|timeout|rejected|denied|invalid)\b/i;

function detectError(result: string): boolean {
  if (!result) return false;
  // Only check the first 200 chars to avoid false positives in long successful results
  const head = result.substring(0, 200);
  return ERROR_PATTERNS.test(head);
}

// ---------- Parse raw -> items ----------

function parseItems(raw: RawTraceMsg[]): TraceItem[] {
  const items: TraceItem[] = [];
  const pendingTools: Map<string, { index: number }> = new Map();

  for (const msg of raw) {
    if (msg.msg_type === 'SystemMessage') {
      items.push({ kind: 'system' });
      continue;
    }

    if (msg.msg_type === 'ResultMessage') {
      items.push({ kind: 'result', text: msg.result || '' });
      continue;
    }

    if (msg.msg_type === 'AssistantMessage' && msg.content) {
      for (const block of msg.content) {
        if (block.type === 'text' && block.text?.trim()) {
          items.push({ kind: 'agent', text: block.text.trim() });
        } else if (block.type === 'tool_use') {
          const toolId = block.id || `tool_${items.length}`;
          const argStr = block.input
            ? (typeof block.input === 'string'
              ? block.input
              : JSON.stringify(block.input, null, 2))
            : '';
          const idx = items.length;
          items.push({ kind: 'tool', name: block.name || 'unknown', args: argStr, result: '', isError: false });
          pendingTools.set(toolId, { index: idx });
        }
      }
      continue;
    }

    if (msg.msg_type === 'UserMessage' && msg.content) {
      for (const block of msg.content) {
        if (block.type === 'tool_result' && block.tool_use_id) {
          const pending = pendingTools.get(block.tool_use_id);
          if (pending) {
            const item = items[pending.index] as Extract<TraceItem, { kind: 'tool' }>;
            item.result = block.content || '';
            item.isError = block.is_error === true || detectError(item.result);
            pendingTools.delete(block.tool_use_id);
          }
        }
      }
      continue;
    }
  }

  // Deduplicate: if the last agent text matches the result text, remove the agent item
  const resultItem = items.find((it) => it.kind === 'result') as Extract<TraceItem, { kind: 'result' }> | undefined;
  if (resultItem) {
    const resultText = resultItem.text.trim();
    for (let i = items.length - 1; i >= 0; i--) {
      const it = items[i];
      if (it.kind === 'agent' && it.text.trim() === resultText) {
        items.splice(i, 1);
        break;
      }
      if (it.kind === 'agent' || it.kind === 'tool') break;
    }
  }

  return items;
}

// ---------- Simple markdown to HTML ----------

function md(text: string): string {
  let html = text;

  html = html.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

  html = html.replace(/```[\s\S]*?```/g, (match) => {
    const code = match.slice(3, -3).replace(/^\w*\n/, '');
    return `<pre><code>${code}</code></pre>`;
  });

  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

  html = html.replace(/^#### (.+)$/gm, '<h4>$1</h4>');
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');

  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');

  html = html.replace(/^---+$/gm, '<hr>');

  html = html.replace(/^(\|.+\|)\n(\|[-| :]+\|)\n((?:\|.+\|\n?)+)/gm, (_match, header: string, _sep: string, body: string) => {
    const thCells = header.split('|').filter((c: string) => c.trim()).map((c: string) => `<th>${c.trim()}</th>`).join('');
    const rows = body.trim().split('\n').map((row: string) => {
      const cells = row.split('|').filter((c: string) => c.trim()).map((c: string) => `<td>${c.trim()}</td>`).join('');
      return `<tr>${cells}</tr>`;
    }).join('');
    return `<table><thead><tr>${thCells}</tr></thead><tbody>${rows}</tbody></table>`;
  });

  html = html.replace(/^(\s*)[-*] (.+)$/gm, '$1<li>$2</li>');
  html = html.replace(/((?:<li>.*<\/li>\n?)+)/g, '<ul>$1</ul>');
  html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');

  html = html.replace(/\n/g, '<br>');

  html = html.replace(/<\/(h[1-4]|ul|ol|table|pre|hr)><br>/g, '</$1>');
  html = html.replace(/<hr><br>/g, '<hr>');
  html = html.replace(/<br><(h[1-4]|ul|ol|table|pre)/g, '<$1');

  return html;
}

// ---------- Tool args summary ----------

function summarizeArgs(name: string, argsJson: string): string {
  try {
    const obj = JSON.parse(argsJson);
    if (name.includes('find_opportunities')) {
      const parts: string[] = [];
      if (obj.max_hours) parts.push(`${obj.max_hours}h`);
      if (obj.min_probability) parts.push(`min=${obj.min_probability}`);
      return parts.join(', ');
    }
    if (name.includes('get_market_details') || name.includes('analyze_opportunity')) {
      return obj.event_slug || '';
    }
    if (name.includes('place_order')) {
      return `${obj.side} ${obj.size} @ ${obj.outcome || ''}`;
    }
    if (name === 'Read') {
      const path = obj.file_path || '';
      return path.split(/[/\\]/).pop() || path;
    }
    if (name === 'Edit') {
      const path = obj.file_path || '';
      return path.split(/[/\\]/).pop() || path;
    }
    if (name === 'WebSearch') {
      return obj.query || '';
    }
    const vals = Object.values(obj).filter((v): v is string => typeof v === 'string');
    return vals[0] || '';
  } catch {
    return argsJson.length > 60 ? argsJson.substring(0, 60) + '...' : argsJson;
  }
}

// ---------- Helpers ----------

function extractDecision(summary: TraceSummary): string {
  const result = (summary as any).result || '';
  const match = result.match(/Decision:\s*\*?\*?(\w+)/i);
  if (match) return match[1].toUpperCase();
  if (result.includes('BUY')) return 'BUY';
  if (result.includes('SELL')) return 'SELL';
  if (result.includes('HOLD')) return 'HOLD';
  return '';
}

// ---------- Component ----------

const Trace = () => {
  const { data: traceList } = usePolling<TraceSummary[]>({
    fetcher: fetchTraceList,
    interval: 60000,
  });

  const [selectedInvoke, setSelectedInvoke] = useState<number | null>(null);
  const [items, setItems] = useState<TraceItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [expandedSet, setExpandedSet] = useState<Set<number>>(new Set());
  const scrollRef = useRef<HTMLDivElement>(null);

  const MAX_RECENT = 50;

  const sortedTraces = traceList
    ? [...traceList].sort((a, b) => b.invoke_num - a.invoke_num).slice(0, MAX_RECENT)
    : [];

  useEffect(() => {
    if (sortedTraces.length > 0 && selectedInvoke === null) {
      setSelectedInvoke(sortedTraces[0].invoke_num);
    }
  }, [sortedTraces.length]);

  useEffect(() => {
    if (selectedInvoke === null) return;
    let cancelled = false;
    setLoading(true);
    setItems([]);
    setExpandedSet(new Set());

    api.get(`/trace/${selectedInvoke}`)
      .then(({ data }) => {
        if (!cancelled) {
          setItems(parseItems(data as RawTraceMsg[]));
          setLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setItems([]);
          setLoading(false);
        }
      });

    return () => { cancelled = true; };
  }, [selectedInvoke]);

  useEffect(() => {
    scrollRef.current?.scrollTo(0, 0);
  }, [items]);

  const toggleExpand = (idx: number) => {
    setExpandedSet((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const selectedSummary = sortedTraces.find((t) => t.invoke_num === selectedInvoke);

  return (
    <div className="trace-page">
      {/* Left sidebar */}
      <div className="trace-sidebar">
        <div className="trace-sidebar-header">
          INVOCATIONS (Last {sortedTraces.length})
        </div>
        <div className="trace-sidebar-list">
          {sortedTraces.map((trace) => {
            const decision = extractDecision(trace);
            return (
              <div
                key={trace.invoke_num}
                className={`trace-sidebar-item ${selectedInvoke === trace.invoke_num ? 'active' : ''}`}
                onClick={() => setSelectedInvoke(trace.invoke_num)}
              >
                <div className="trace-sidebar-item-header">
                  <span className="trace-sidebar-num">#{trace.invoke_num}</span>
                  <span className="trace-sidebar-date">
                    {dayjs(trace.date, 'YYYY-MM-DD').format('MM/DD')}
                  </span>
                </div>
                {decision && (
                  <div className="trace-sidebar-decision">{decision}</div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Right: dark content area */}
      <div className="trace-chat">
        {selectedInvoke !== null && selectedSummary && (
          <div className="trace-chat-header">
            <span className="trace-chat-title">Invoke #{selectedInvoke}</span>
            <span className="trace-chat-meta">
              {(selectedSummary as any).num_turns || 0} turns
              {(selectedSummary as any).duration_ms
                ? ` / ${Math.round((selectedSummary as any).duration_ms / 1000)}s`
                : ''}
              {(selectedSummary as any).total_cost_usd
                ? ` / $${(selectedSummary as any).total_cost_usd.toFixed(3)}`
                : ''}
            </span>
          </div>
        )}

        {selectedInvoke === null ? (
          <div className="trace-chat-empty">Select an invocation from the left</div>
        ) : loading ? (
          <div className="trace-loading">Loading trace #{selectedInvoke}...</div>
        ) : items.length === 0 ? (
          <div className="trace-chat-empty">No messages in this trace</div>
        ) : (
          <div className="trace-chat-messages" ref={scrollRef}>
            {items.map((item, idx) => {
              if (item.kind === 'system') {
                return (
                  <div key={idx} className="trace-system">
                    --- system prompt ---
                  </div>
                );
              }

              if (item.kind === 'agent') {
                return (
                  <div
                    key={idx}
                    className="trace-agent"
                    dangerouslySetInnerHTML={{ __html: md(item.text) }}
                  />
                );
              }

              if (item.kind === 'tool') {
                const isExpanded = expandedSet.has(idx);
                const summary = summarizeArgs(item.name, item.args);

                return (
                  <div key={idx} className="trace-tool">
                    <div
                      className="trace-tool-header"
                      onClick={() => toggleExpand(idx)}
                    >
                      <span className={`trace-tool-dot ${item.isError ? 'error' : 'success'}`} />
                      <span className="trace-tool-name">{item.name}</span>
                      {summary && <span className="trace-tool-args">{summary}</span>}
                      <span className={`trace-tool-arrow ${isExpanded ? 'open' : ''}`}>
                        &#x25BC;
                      </span>
                    </div>
                    {isExpanded && item.result && (
                      <div className="trace-tool-result">
                        <div className="trace-tool-result-text">
                          {item.result}
                        </div>
                      </div>
                    )}
                  </div>
                );
              }

              if (item.kind === 'result') {
                return (
                  <div key={idx} className="trace-result">
                    <div className="trace-result-label">Final Result</div>
                    <div
                      className="trace-agent"
                      dangerouslySetInnerHTML={{ __html: md(item.text) }}
                    />
                  </div>
                );
              }

              return null;
            })}
          </div>
        )}
      </div>
    </div>
  );
};

export default Trace;

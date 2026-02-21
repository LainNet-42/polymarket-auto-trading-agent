import { useState, useEffect } from 'react';
import { fetchTrace, TraceMessage } from '../../services/api';
import './TraceViewer.css';

interface Props {
  invokeNum: number;
}

const TraceViewer = ({ invokeNum }: Props) => {
  const [messages, setMessages] = useState<TraceMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetchTrace(invokeNum)
      .then((data) => {
        if (!cancelled) {
          setMessages(data);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err.message || 'Failed to load trace');
          setLoading(false);
        }
      });

    return () => { cancelled = true; };
  }, [invokeNum]);

  if (loading) {
    return <div className="trace-viewer-loading">Loading trace #{invokeNum}...</div>;
  }

  if (error) {
    return <div className="trace-viewer-error">Error: {error}</div>;
  }

  if (messages.length === 0) {
    return <div className="trace-viewer-empty">No messages in trace #{invokeNum}</div>;
  }

  return (
    <div className="trace-viewer">
      {messages.map((msg, i) => (
        <div key={i} className={`trace-message trace-role-${msg.role}`}>
          <div className="trace-message-header">
            <span className="trace-role">[{msg.role}]</span>
            {msg.tool_name && <span className="trace-tool-name">{msg.tool_name}</span>}
          </div>
          {msg.content && (
            <div className="trace-content">
              {msg.content.length > 500 ? msg.content.substring(0, 500) + '...' : msg.content}
            </div>
          )}
          {msg.tool_input && (
            <div className="trace-tool-input">
              <span className="trace-label">Input:</span>
              <pre>{typeof msg.tool_input === 'string'
                ? (msg.tool_input.length > 300 ? msg.tool_input.substring(0, 300) + '...' : msg.tool_input)
                : JSON.stringify(msg.tool_input, null, 2).substring(0, 300)
              }</pre>
            </div>
          )}
          {msg.tool_result && (
            <div className="trace-tool-result">
              <span className="trace-label">Result:</span>
              <pre>{typeof msg.tool_result === 'string'
                ? (msg.tool_result.length > 300 ? msg.tool_result.substring(0, 300) + '...' : msg.tool_result)
                : JSON.stringify(msg.tool_result, null, 2).substring(0, 300)
              }</pre>
            </div>
          )}
        </div>
      ))}
    </div>
  );
};

export default TraceViewer;

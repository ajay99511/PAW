/**
 * Agent Trace Visualization Component
 * 
 * Displays the agent execution trace showing:
 * - Planner → Researcher → Synthesizer flow
 * - Tool calls and results
 * - Timing information
 */

import { useState, useEffect } from 'react';

interface TraceEvent {
  run_id: string;
  agent_name: string;
  event_type: string;
  content: string;
  timestamp: string;
  metadata: Record<string, unknown>;
}

interface Props {
  runId: string | null;
}

export default function AgentTrace({ runId }: Props) {
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    if (!runId) {
      setEvents([]);
      setConnected(false);
      return;
    }

    // Connect to SSE stream
    const eventSource = new EventSource(
      `http://127.0.0.1:8000/agents/trace/${runId}`
    );

    eventSource.onopen = () => {
      setConnected(true);
      setEvents([]);
    };

    eventSource.onmessage = (event) => {
      try {
        const traceEvent: TraceEvent = JSON.parse(event.data);
        setEvents((prev) => [...prev, traceEvent]);
      } catch (err) {
        console.error('Failed to parse trace event:', err);
      }
    };

    eventSource.onerror = () => {
      setConnected(false);
      eventSource.close();
    };

    return () => {
      eventSource.close();
    };
  }, [runId]);

  if (!runId) {
    return (
      <div className="empty-state">
        <div className="empty-state-icon">🔍</div>
        <div className="empty-state-title">No Active Trace</div>
        <div className="empty-state-text">
          Run an agent to see the execution trace
        </div>
      </div>
    );
  }

  return (
    <div style={{ padding: '16px' }}>
      <div style={{ 
        display: 'flex', 
        justifyContent: 'space-between', 
        alignItems: 'center',
        marginBottom: '16px'
      }}>
        <h3 style={{ margin: 0 }}>Agent Execution Trace</h3>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <span style={{ 
            fontSize: '12px', 
            color: connected ? 'var(--success-color)' : 'var(--text-muted)'
          }}>
            {connected ? '● Live' : '○ Disconnected'}
          </span>
          <span className="badge badge-accent">{events.length} events</span>
        </div>
      </div>

      {events.length === 0 ? (
        <div className="empty-state">
          <div className="spinner" />
          <div>Waiting for agent events...</div>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          {events.map((event, index) => (
            <TraceEventCard key={index} event={event} />
          ))}
        </div>
      )}
    </div>
  );
}

function TraceEventCard({ event }: { event: TraceEvent }) {
  const [expanded, setExpanded] = useState(false);

  const getAgentColor = (agentName: string) => {
    switch (agentName) {
      case 'planner':
        return 'var(--accent-color)';
      case 'researcher':
        return 'var(--success-color)';
      case 'synthesizer':
        return 'var(--warning-color)';
      case 'system':
        return 'var(--text-muted)';
      default:
        return 'var(--text)';
    }
  };

  const getEventIcon = (eventType: string) => {
    switch (eventType) {
      case 'thinking':
        return '💭';
      case 'output':
        return '📝';
      case 'tool_result':
        return '🔧';
      case 'error':
        return '⚠️';
      default:
        return '📌';
    }
  };

  const time = new Date(event.timestamp).toLocaleTimeString();

  return (
    <div
      style={{
        background: 'var(--bg-secondary)',
        border: `1px solid ${getAgentColor(event.agent_name)}`,
        borderRadius: '8px',
        padding: '12px',
        transition: 'all 0.2s ease',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <span style={{ fontSize: '16px' }}>
            {getEventIcon(event.event_type)}
          </span>
          <div>
            <div style={{ 
              fontSize: '12px', 
              fontWeight: 600,
              color: getAgentColor(event.agent_name),
              textTransform: 'uppercase',
            }}>
              {event.agent_name}
            </div>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
              {event.event_type} • {time}
            </div>
          </div>
        </div>

        {event.metadata && Object.keys(event.metadata).length > 0 && (
          <button
            onClick={() => setExpanded(!expanded)}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-muted)',
              cursor: 'pointer',
              fontSize: '12px',
            }}
          >
            {expanded ? '▼' : '▶'}
          </button>
        )}
      </div>

      <div style={{ 
        marginTop: '8px', 
        fontSize: '13px', 
        lineHeight: 1.5,
        whiteSpace: 'pre-wrap',
        color: 'var(--text)',
      }}>
        {event.content}
      </div>

      {expanded && event.metadata && (
        <div style={{
          marginTop: '12px',
          padding: '8px',
          background: 'var(--bg-input)',
          borderRadius: '4px',
          fontSize: '11px',
          fontFamily: 'monospace',
          overflow: 'auto',
          maxHeight: '200px',
        }}>
          <pre style={{ margin: 0 }}>
            {JSON.stringify(event.metadata, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

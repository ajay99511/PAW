/**
 * A2A Agents Tab Component
 * 
 * Displays registered Tier 1 agents and allows task delegation.
 */

import { useState, useEffect } from "react";
import {
  listA2AAgents,
  delegateA2ATask,
  getA2ATaskStatus,
  type A2AAgentCard,
  type A2ATaskHandle,
} from "../../lib/api";

export default function A2AAgentsTab() {
  const [agents, setAgents] = useState<A2AAgentCard[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [taskInput, setTaskInput] = useState("");
  const [taskResult, setTaskResult] = useState<A2ATaskHandle | null>(null);
  const [delegating, setDelegating] = useState(false);

  useEffect(() => {
    loadAgents();
  }, []);

  const loadAgents = async () => {
    setLoading(true);
    try {
      const data = await listA2AAgents();
      setAgents(data.agents || []);
    } catch (err) {
      console.error('Failed to load A2A agents:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleDelegate = async (agentId: string) => {
    if (!taskInput.trim()) return;

    setDelegating(true);
    setTaskResult(null);
    
    try {
      const result = await delegateA2ATask(agentId, {
        path: taskInput,
        focus: 'all',
      });
      setTaskResult(result);
      
      // Poll for task completion
      pollTaskStatus(result.task_id);
    } catch (err) {
      console.error('Failed to delegate task:', err);
      setTaskResult({
        task_id: '',
        agent_id: agentId,
        status: 'failed',
        error: err instanceof Error ? err.message : 'Unknown error',
      });
    } finally {
      setDelegating(false);
    }
  };

  const pollTaskStatus = async (taskId: string) => {
    const poll = async () => {
      try {
        const data = await getA2ATaskStatus(taskId);
        
        setTaskResult(data);
        
        if (data.status === 'completed' || data.status === 'failed') {
          return; // Stop polling
        }
        
        // Continue polling every 2 seconds
        setTimeout(poll, 2000);
      } catch (err) {
        console.error('Failed to poll task status:', err);
      }
    };
    
    poll();
  };

  const getCapabilityColor = (capability: string) => {
    switch (capability) {
      case 'code_review':
      case 'security_scan':
        return 'var(--error-color)';
      case 'workspace_analysis':
      case 'dependency_audit':
        return 'var(--accent-color)';
      case 'test_generation':
        return 'var(--success-color)';
      default:
        return 'var(--text)';
    }
  };

  return (
    <div>
      <div style={{ marginBottom: '24px' }}>
        <h3 style={{ margin: '0 0 8px 0' }}>A2A Agent Registry</h3>
        <p style={{ fontSize: '13px', color: 'var(--text-muted)', margin: 0 }}>
          Discover and delegate tasks to specialized Tier 1 agents
        </p>
      </div>

      {loading ? (
        <div className="empty-state">
          <div className="spinner" />
          <div>Loading agents...</div>
        </div>
      ) : agents.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon">🤖</div>
          <div className="empty-state-title">No Agents Registered</div>
          <div className="empty-state-text">
            A2A agents will be automatically registered when the system starts
          </div>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: '16px' }}>
          {agents.map((agent) => (
            <div
              key={agent.agent_id}
              className="card"
              style={{
                background: 'var(--bg-secondary)',
                padding: '16px',
                borderRadius: '8px',
                border: `2px solid ${agent.enabled ? 'var(--success-color)' : 'var(--text-muted)'}`,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '12px' }}>
                <div>
                  <div style={{ fontSize: '16px', fontWeight: 700, marginBottom: '4px' }}>
                    {agent.name}
                  </div>
                  <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                    {agent.agent_id}
                  </div>
                </div>
                <span className={`badge ${agent.enabled ? 'badge-success' : 'badge-secondary'}`}>
                  {agent.enabled ? '✅ Active' : '⏸️ Inactive'}
                </span>
              </div>

              <div style={{ fontSize: '13px', marginBottom: '12px', lineHeight: 1.5 }}>
                {agent.description}
              </div>

              {/* Capabilities */}
              <div style={{ marginBottom: '12px' }}>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px' }}>
                  Capabilities
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                  {agent.capabilities.map((cap) => (
                    <span
                      key={cap}
                      className="badge badge-accent"
                      style={{
                        background: `${getCapabilityColor(cap)}20`,
                        color: getCapabilityColor(cap),
                        fontSize: '10px',
                      }}
                    >
                      {cap.replace(/_/g, ' ')}
                    </span>
                  ))}
                </div>
              </div>

              {/* Permissions */}
              <div style={{ marginBottom: '16px', fontSize: '11px', color: 'var(--text-muted)' }}>
                <div>Read: {agent.permissions.read.join(', ') || 'None'}</div>
                <div>Write: {agent.permissions.write.join(', ') || 'None'}</div>
                <div>Execute: {agent.permissions.execute ? '✅ Yes' : '❌ No'}</div>
              </div>

              {/* Delegate Button */}
              <button
                className="btn btn-primary"
                onClick={() => setSelectedAgent(agent.agent_id)}
                disabled={!agent.enabled}
                style={{ width: '100%' }}
              >
                Delegate Task
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Task Delegation Modal */}
      {selectedAgent && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: 'rgba(0,0,0,0.5)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
          }}
          onClick={() => setSelectedAgent(null)}
        >
          <div
            style={{
              background: 'var(--bg-secondary)',
              padding: '24px',
              borderRadius: '12px',
              maxWidth: '500px',
              width: '90%',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 style={{ marginTop: 0 }}>Delegate Task</h3>
            
            <div style={{ marginBottom: '16px' }}>
              <div style={{ fontSize: '13px', color: 'var(--text-muted)', marginBottom: '8px' }}>
                Selected Agent: <strong>{selectedAgent}</strong>
              </div>
              
              <label style={{ display: 'block', marginBottom: '8px', fontSize: '13px' }}>
                Task Description
              </label>
              <textarea
                className="input"
                value={taskInput}
                onChange={(e) => setTaskInput(e.target.value)}
                placeholder="Describe the task you want the agent to perform..."
                rows={4}
                style={{ width: '100%', resize: 'vertical' }}
              />
            </div>

            {taskResult && (
              <div style={{
                marginBottom: '16px',
                padding: '12px',
                borderRadius: '8px',
                background: taskResult.status === 'completed' ? 'rgba(0,255,0,0.1)' :
                           taskResult.status === 'failed' ? 'rgba(255,0,0,0.1)' :
                           'rgba(255,255,0,0.1)',
                border: `1px solid ${
                  taskResult.status === 'completed' ? 'var(--success-color)' :
                  taskResult.status === 'failed' ? 'var(--error-color)' :
                  'var(--warning-color)'
                }`,
              }}>
                <div style={{ fontSize: '12px', fontWeight: 600, marginBottom: '4px' }}>
                  Task Status: {taskResult.status.toUpperCase()}
                </div>
                {taskResult.error && (
                  <div style={{ fontSize: '11px', color: 'var(--error-color)' }}>
                    {taskResult.error}
                  </div>
                )}
                {taskResult.result && (
                  <details style={{ marginTop: '8px' }}>
                    <summary style={{ fontSize: '11px', cursor: 'pointer' }}>View Result</summary>
                    <pre style={{
                      marginTop: '8px',
                      fontSize: '10px',
                      fontFamily: 'monospace',
                      background: 'var(--bg-input)',
                      padding: '8px',
                      borderRadius: '4px',
                      overflow: 'auto',
                      maxHeight: '200px',
                    }}>
                      {JSON.stringify(taskResult.result, null, 2)}
                    </pre>
                  </details>
                )}
              </div>
            )}

            <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end' }}>
              <button
                className="btn btn-secondary"
                onClick={() => setSelectedAgent(null)}
              >
                Close
              </button>
              <button
                className="btn btn-primary"
                onClick={() => handleDelegate(selectedAgent)}
                disabled={delegating || !taskInput.trim()}
              >
                {delegating ? 'Delegating...' : 'Delegate Task'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

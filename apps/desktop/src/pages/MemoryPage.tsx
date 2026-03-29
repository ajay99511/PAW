/**
 * Memory Page - Expanded to show all 5 layers
 * 
 * Tabs:
 * - Facts (Mem0) - User-centric facts
 * - Sessions - JSONL session transcripts
 * - Bootstrap - Bootstrap files viewer
 * - Compaction - Compaction history
 * - Search - LTM hybrid search
 */

import { useState, useEffect } from "react";
import { useMemories, useMemoryHealth } from "../lib/hooks";
import {
  listMemorySessions,
  getSessionTranscript,
  getMemoryBootstrap,
  getCompactionHistory,
  searchMemoryLayers,
  type MemoryBootstrapResponse,
  type MemoryCompactionResponse,
  type MemorySearchResponse,
  type SessionTranscriptEntry,
} from "../lib/api";

type MemoryTab = 'facts' | 'sessions' | 'bootstrap' | 'compaction' | 'search';

interface Session {
  session_id: string;
  entries?: SessionTranscriptEntry[];
  count?: number;
}

export default function MemoryPage() {
  const [activeTab, setActiveTab] = useState<MemoryTab>('facts');
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selectedSession, setSelectedSession] = useState<string | null>(null);
  const [sessionTranscript, setSessionTranscript] = useState<SessionTranscriptEntry[]>([]);
  const [bootstrapData, setBootstrapData] = useState<MemoryBootstrapResponse | null>(null);
  const [compactionData, setCompactionData] = useState<MemoryCompactionResponse | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<MemorySearchResponse | null>(null);
  const [loading, setLoading] = useState(false);

  // Use existing hooks for Mem0 facts
  const { data: memoriesData, isLoading: memoriesLoading } = useMemories();
  useMemoryHealth();

  // Load sessions
  useEffect(() => {
    if (activeTab === 'sessions') {
      loadSessions();
    }
  }, [activeTab]);

  // Load bootstrap files
  useEffect(() => {
    if (activeTab === 'bootstrap') {
      loadBootstrapFiles();
    }
  }, [activeTab]);

  // Load compaction history
  useEffect(() => {
    if (activeTab === 'compaction') {
      loadCompactionHistory();
    }
  }, [activeTab]);

  const loadSessions = async () => {
    setLoading(true);
    try {
      const data = await listMemorySessions();
      const sessionItems = Array.isArray(data.sessions)
        ? data.sessions.map((sessionId) => ({ session_id: sessionId }))
        : [];
      setSessions(sessionItems);
    } catch (err) {
      console.error('Failed to load sessions:', err);
    } finally {
      setLoading(false);
    }
  };

  const loadSessionTranscript = async (sessionId: string) => {
    setLoading(true);
    try {
      const data = await getSessionTranscript(sessionId, 50);
      setSessionTranscript(data.entries || []);
      setSelectedSession(sessionId);
    } catch (err) {
      console.error('Failed to load session transcript:', err);
    } finally {
      setLoading(false);
    }
  };

  const loadBootstrapFiles = async () => {
    setLoading(true);
    try {
      const data = await getMemoryBootstrap();
      setBootstrapData(data);
    } catch (err) {
      console.error('Failed to load bootstrap files:', err);
    } finally {
      setLoading(false);
    }
  };

  const loadCompactionHistory = async () => {
    setLoading(true);
    try {
      const data = await getCompactionHistory();
      setCompactionData(data);
    } catch (err) {
      console.error('Failed to load compaction history:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchQuery.trim()) return;

    setLoading(true);
    try {
      const data = await searchMemoryLayers(searchQuery, 10);
      setSearchResults(data);
    } catch (err) {
      console.error('Failed to search:', err);
    } finally {
      setLoading(false);
    }
  };

  const renderTabContent = () => {
    switch (activeTab) {
      case 'facts':
        return renderFactsTab();
      case 'sessions':
        return renderSessionsTab();
      case 'bootstrap':
        return renderBootstrapTab();
      case 'compaction':
        return renderCompactionTab();
      case 'search':
        return renderSearchTab();
      default:
        return null;
    }
  };

  const renderFactsTab = () => {
    const memories = memoriesData?.memories || [];

    return (
      <div>
        <div style={{ marginBottom: '16px' }}>
          <h3 style={{ margin: '0 0 8px 0' }}>Mem0 Facts</h3>
          <p style={{ fontSize: '13px', color: 'var(--text-muted)', margin: 0 }}>
            User-centric facts extracted from conversations
          </p>
        </div>

        {memoriesLoading ? (
          <div className="empty-state">
            <div className="spinner" />
            <div>Loading memories...</div>
          </div>
        ) : memories.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon">🧠</div>
            <div className="empty-state-title">No Memories Yet</div>
            <div className="empty-state-text">
              Memories will be automatically extracted from your conversations
            </div>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {memories.map((memory: any, index: number) => (
              <div
                key={memory.id || index}
                style={{
                  background: 'var(--bg-secondary)',
                  padding: '12px',
                  borderRadius: '8px',
                  border: '1px solid var(--border)',
                }}
              >
                <div style={{ fontSize: '13px', marginBottom: '4px' }}>
                  {memory.memory || memory.content}
                </div>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                  {memory.metadata?.memory_type && (
                    <span className="badge badge-accent" style={{ marginRight: '8px' }}>
                      {memory.metadata.memory_type}
                    </span>
                  )}
                  {memory.score && <span>Score: {(memory.score * 100).toFixed(0)}%</span>}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  };

  const renderSessionsTab = () => {
    return (
      <div style={{ display: 'flex', gap: '16px', height: 'calc(100vh - 200px)' }}>
        {/* Sessions List */}
        <div style={{ width: '300px', borderRight: '1px solid var(--border)', paddingRight: '16px' }}>
          <h3 style={{ margin: '0 0 16px 0' }}>Session Transcripts</h3>
          
          {loading ? (
            <div className="empty-state">
              <div className="spinner" />
              <div>Loading...</div>
            </div>
          ) : sessions.length === 0 ? (
            <div className="empty-state">
              <div>No sessions yet</div>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {sessions.map((session) => (
                <button
                  key={session.session_id}
                  className={`btn ${selectedSession === session.session_id ? 'btn-primary' : 'btn-secondary'}`}
                  onClick={() => loadSessionTranscript(session.session_id)}
                  style={{ justifyContent: 'flex-start', textAlign: 'left' }}
                >
                  <div style={{ fontSize: '12px' }}>
                    {session.session_id.length > 30 
                      ? session.session_id.substring(0, 30) + '...'
                      : session.session_id}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Session Transcript */}
        <div style={{ flex: 1, overflow: 'auto' }}>
          {selectedSession ? (
            <div>
              <h3 style={{ margin: '0 0 16px 0' }}>Transcript: {selectedSession}</h3>
              
              {sessionTranscript.length === 0 ? (
                <div className="empty-state">
                  <div>No entries in this session</div>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  {sessionTranscript.map((entry: any, index: number) => (
                    <div
                      key={entry.id || index}
                      style={{
                        background: 'var(--bg-secondary)',
                        padding: '12px',
                        borderRadius: '8px',
                        border: `1px solid var(--border)`,
                      }}
                    >
                      <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px' }}>
                        <span className="badge badge-accent">{entry.type}</span>
                        {' '}{new Date(entry.timestamp).toLocaleString()}
                      </div>
                      <div style={{ fontSize: '13px', whiteSpace: 'pre-wrap' }}>
                        {JSON.stringify(entry.content, null, 2)}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className="empty-state">
              <div className="empty-state-icon">📋</div>
              <div className="empty-state-title">Select a Session</div>
              <div className="empty-state-text">
                Choose a session from the list to view its transcript
              </div>
            </div>
          )}
        </div>
      </div>
    );
  };

  const renderBootstrapTab = () => {
    return (
      <div>
        <h3 style={{ margin: '0 0 16px 0' }}>Bootstrap Files</h3>
        
        {loading ? (
          <div className="empty-state">
            <div className="spinner" />
            <div>Loading...</div>
          </div>
        ) : !bootstrapData ? (
          <div className="empty-state">
            <div>No bootstrap data</div>
          </div>
        ) : (
          <div>
            {/* Summary */}
            <div style={{ 
              display: 'grid', 
              gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
              gap: '16px',
              marginBottom: '24px',
            }}>
              <div className="card" style={{ background: 'var(--bg-secondary)', padding: '16px' }}>
                <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '8px' }}>
                  Total Files
                </div>
                <div style={{ fontSize: '24px', fontWeight: 700 }}>
                  {bootstrapData.summary?.total_files || 0}
                </div>
              </div>
              
              <div className="card" style={{ background: 'var(--bg-secondary)', padding: '16px' }}>
                <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '8px' }}>
                  Total Characters
                </div>
                <div style={{ fontSize: '24px', fontWeight: 700 }}>
                  {bootstrapData.summary?.total_chars || 0}
                </div>
              </div>
            </div>

            {/* File Contents */}
            {bootstrapData.content && (
              <div style={{ 
                background: 'var(--bg-input)', 
                padding: '16px', 
                borderRadius: '8px',
                fontFamily: 'monospace',
                fontSize: '12px',
                whiteSpace: 'pre-wrap',
                overflow: 'auto',
                maxHeight: 'calc(100vh - 400px)',
              }}>
                {bootstrapData.content}
              </div>
            )}
          </div>
        )}
      </div>
    );
  };

  const renderCompactionTab = () => {
    return (
      <div>
        <h3 style={{ margin: '0 0 16px 0' }}>Compaction History</h3>
        
        {loading ? (
          <div className="empty-state">
            <div className="spinner" />
            <div>Loading...</div>
          </div>
        ) : !compactionData ? (
          <div className="empty-state">
            <div>No compaction data</div>
          </div>
        ) : (
          <div>
            {/* Summary */}
            <div style={{ 
              display: 'grid', 
              gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
              gap: '16px',
              marginBottom: '24px',
            }}>
              <div className="card" style={{ background: 'var(--bg-secondary)', padding: '16px' }}>
                <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '8px' }}>
                  Total Sessions
                </div>
                <div style={{ fontSize: '24px', fontWeight: 700 }}>
                  {compactionData.total_sessions || 0}
                </div>
              </div>
              
              <div className="card" style={{ background: 'var(--bg-secondary)', padding: '16px' }}>
                <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '8px' }}>
                  Total Compactions
                </div>
                <div style={{ fontSize: '24px', fontWeight: 700 }}>
                  {compactionData.total_compactions || 0}
                </div>
              </div>
            </div>

            {/* Recent Sessions */}
            {compactionData.compactions && compactionData.compactions.length > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {compactionData.compactions.map((compaction: any, index: number) => (
                  <div
                    key={compaction.id || index}
                    style={{
                      background: 'var(--bg-secondary)',
                      padding: '12px',
                      borderRadius: '8px',
                      border: '1px solid var(--border)',
                    }}
                  >
                    <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px' }}>
                      {new Date(compaction.timestamp).toLocaleString()}
                    </div>
                    <div style={{ fontSize: '13px' }}>
                      {compaction.content.summary || 'No summary available'}
                    </div>
                    <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '8px' }}>
                      Entries removed: {compaction.content.entries_removed || 'N/A'}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="empty-state">
                <div className="empty-state-icon">📦</div>
                <div className="empty-state-title">No Compactions Yet</div>
                <div className="empty-state-text">
                  Compaction will automatically trigger when sessions approach token limits
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    );
  };

  const renderSearchTab = () => {
    return (
      <div>
        <h3 style={{ margin: '0 0 16px 0' }}>Search Long-Term Memory</h3>
        
        {/* Search Form */}
        <form onSubmit={handleSearch} style={{ marginBottom: '24px' }}>
          <div style={{ display: 'flex', gap: '12px' }}>
            <input
              type="text"
              className="input"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search across all memory layers..."
              style={{ flex: 1 }}
            />
            <button type="submit" className="btn btn-primary" disabled={loading || !searchQuery.trim()}>
              {loading ? 'Searching...' : '🔍 Search'}
            </button>
          </div>
        </form>

        {/* Search Results */}
        {searchResults && (
          <div>
            <div style={{ fontSize: '13px', color: 'var(--text-muted)', marginBottom: '16px' }}>
              Query: "{searchQuery}"
            </div>
            
            {searchResults.context ? (
              <div style={{ 
                background: 'var(--bg-secondary)', 
                padding: '16px', 
                borderRadius: '8px',
                whiteSpace: 'pre-wrap',
                fontSize: '13px',
                lineHeight: 1.6,
              }}>
                {searchResults.context}
              </div>
            ) : (
              <div className="empty-state">
                <div>No results found</div>
              </div>
            )}
          </div>
        )}
      </div>
    );
  };

  return (
    <div style={{ padding: '20px', height: '100%', overflow: 'auto' }}>
      {/* Tabs */}
      <div style={{ 
        display: 'flex', 
        gap: '8px', 
        marginBottom: '24px',
        borderBottom: '1px solid var(--border)',
        paddingBottom: '12px',
      }}>
        <button
          className={`btn ${activeTab === 'facts' ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setActiveTab('facts')}
        >
          🧠 Facts
        </button>
        <button
          className={`btn ${activeTab === 'sessions' ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setActiveTab('sessions')}
        >
          📋 Sessions
        </button>
        <button
          className={`btn ${activeTab === 'bootstrap' ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setActiveTab('bootstrap')}
        >
          📁 Bootstrap
        </button>
        <button
          className={`btn ${activeTab === 'compaction' ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setActiveTab('compaction')}
        >
          📦 Compaction
        </button>
        <button
          className={`btn ${activeTab === 'search' ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setActiveTab('search')}
        >
          🔍 Search
        </button>
      </div>

      {/* Tab Content */}
      {renderTabContent()}
    </div>
  );
}

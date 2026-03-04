import { useState, useEffect, useCallback } from "react";
import {
    getAllMemories,
    forgetMemory,
    consolidateMemories,
    checkMemoryHealth,
    type Memory,
} from "../lib/api";

export default function MemoryPage() {
    const [memories, setMemories] = useState<Memory[]>([]);
    const [filter, setFilter] = useState("");
    const [loading, setLoading] = useState(false);
    const [qdrantOnline, setQdrantOnline] = useState(false);
    const [consolidating, setConsolidating] = useState(false);

    const fetchMemories = useCallback(async () => {
        setLoading(true);
        try {
            const data = await getAllMemories();
            setMemories(data.memories || []);
        } catch (err) {
            console.error("Failed to fetch memories:", err);
            setMemories([]);
        } finally {
            setLoading(false);
        }
    }, []);

    const fetchHealth = useCallback(async () => {
        try {
            const h = await checkMemoryHealth();
            setQdrantOnline(h.status === "ok");
        } catch {
            setQdrantOnline(false);
        }
    }, []);

    useEffect(() => {
        fetchMemories();
        fetchHealth();
    }, [fetchMemories, fetchHealth]);

    const handleForget = async (id: string) => {
        try {
            await forgetMemory(id);
            setMemories((prev) => prev.filter((m) => m.id !== id));
        } catch (err) {
            console.error("Failed to forget memory:", err);
        }
    };

    const handleConsolidate = async () => {
        setConsolidating(true);
        try {
            await consolidateMemories();
            await fetchMemories();
        } catch (err) {
            console.error("Consolidation failed:", err);
        } finally {
            setConsolidating(false);
        }
    };

    const filtered = memories.filter((m) => {
        const text = m.memory || m.content || "";
        return text.toLowerCase().includes(filter.toLowerCase());
    });

    return (
        <>
            <div className="page-header">
                <div>
                    <div className="page-title">Memory</div>
                    <div className="page-subtitle">
                        View and manage what PersonalAssist has learned about you
                    </div>
                </div>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <span
                        className={`status-dot ${qdrantOnline ? "online" : "offline"}`}
                    />
                    <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
                        Qdrant {qdrantOnline ? "Connected" : "Offline"}
                    </span>
                </div>
            </div>

            <div className="page-body">
                {/* Stats */}
                <div className="stats-row">
                    <div className="card stat-card">
                        <div className="stat-value">{memories.length}</div>
                        <div className="stat-label">Total Memories</div>
                    </div>
                    <div className="card stat-card">
                        <div className="stat-value">{filtered.length}</div>
                        <div className="stat-label">Shown</div>
                    </div>
                </div>

                {/* Controls */}
                <div
                    style={{
                        display: "flex",
                        gap: 10,
                        marginBottom: 16,
                        alignItems: "center",
                    }}
                >
                    <div className="search-bar" style={{ flex: 1, marginBottom: 0 }}>
                        <span className="search-bar-icon">🔍</span>
                        <input
                            className="input"
                            placeholder="Filter memories..."
                            value={filter}
                            onChange={(e) => setFilter(e.target.value)}
                            id="memory-search"
                        />
                    </div>
                    <button
                        className="btn btn-secondary"
                        onClick={fetchMemories}
                        disabled={loading}
                        id="memory-refresh"
                    >
                        {loading ? <span className="spinner" /> : "↻ Refresh"}
                    </button>
                    <button
                        className="btn btn-primary"
                        onClick={handleConsolidate}
                        disabled={consolidating}
                        id="memory-consolidate"
                    >
                        {consolidating ? <span className="spinner" /> : "🔗 Consolidate"}
                    </button>
                </div>

                {/* Memory List */}
                {filtered.length === 0 && !loading ? (
                    <div className="empty-state">
                        <div className="empty-state-icon">🧠</div>
                        <div className="empty-state-title">No Memories Yet</div>
                        <div className="empty-state-text">
                            {filter
                                ? "No memories match your filter."
                                : "Start chatting to build up memories. PersonalAssist learns from every conversation."}
                        </div>
                    </div>
                ) : (
                    <div className="memory-list">
                        {filtered.map((m, i) => (
                            <div className="memory-item" key={m.id || i}>
                                <div className="memory-text">{m.memory || m.content}</div>
                                <button
                                    className="btn btn-danger btn-sm"
                                    onClick={() => handleForget(m.id)}
                                    title="Forget this memory"
                                    id={`memory-forget-${i}`}
                                >
                                    ✕
                                </button>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </>
    );
}

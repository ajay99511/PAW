import { useState, useEffect, useCallback } from "react";
import {
    listModels,
    getActiveModel,
    switchModel,
    type ModelInfo,
} from "../lib/api";

export default function ModelsPage() {
    const [models, setModels] = useState<ModelInfo[]>([]);
    const [activeModelId, setActiveModelId] = useState("");
    const [loading, setLoading] = useState(false);
    const [switching, setSwitching] = useState<string | null>(null);

    const fetchModels = useCallback(async () => {
        setLoading(true);
        try {
            const [modelData, activeData] = await Promise.all([
                listModels(),
                getActiveModel(),
            ]);
            setModels(modelData.models || []);
            setActiveModelId(activeData.active_model || "");
        } catch (err) {
            console.error("Failed to fetch models:", err);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchModels();
    }, [fetchModels]);

    const handleSwitch = async (modelId: string) => {
        setSwitching(modelId);
        try {
            const result = await switchModel(modelId);
            setActiveModelId(result.active_model);
        } catch (err) {
            console.error("Failed to switch model:", err);
        } finally {
            setSwitching(null);
        }
    };

    const localModels = models.filter((m) => m.is_local);
    const geminiModels = models.filter((m) => !m.is_local && m.provider === 'gemini');
    const otherRemote = models.filter((m) => !m.is_local && m.provider !== 'gemini');

    const renderModelCard = (m: ModelInfo) => {
        const isActive = m.id === activeModelId || m.is_active;
        const isSwitching = switching === m.id;

        return (
            <div
                key={m.id}
                className={`card model-card ${isActive ? "active" : ""}`}
                onClick={() => !isSwitching && handleSwitch(m.id)}
            >
                <div className="model-card-header">
                    <div className="model-name" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        {m.name || m.id}
                        {m.is_recommended && <span title="Recommended for cost-efficiency" style={{ fontSize: '14px' }}>⭐</span>}
                    </div>
                    <div style={{ display: "flex", gap: 6 }}>
                        {isActive && <span className="badge badge-success">Active</span>}
                        {m.is_local ? (
                            <span className="badge badge-info">Local</span>
                        ) : (
                            <span className="badge badge-warning">Remote</span>
                        )}
                    </div>
                </div>

                {m.description && (
                    <div className="model-detail" style={{ marginBottom: 8, color: 'var(--text-secondary)' }}>
                        {m.description}
                    </div>
                )}

                <div className="model-detail">
                    <strong>Provider:</strong> {m.provider}
                </div>

                {m.context_window && (
                    <div className="model-detail">
                        <strong>Context Window:</strong> {m.context_window}
                    </div>
                )}

                {/* Pricing section if available */}
                {(m.pricing_input || m.pricing_output) && (
                    <div className="model-detail" style={{ display: 'flex', gap: '12px', marginTop: '6px' }}>
                        {m.pricing_input && (
                            <span className="badge" style={{ background: 'var(--bg-glass)' }}>
                                IN: {m.pricing_input}
                            </span>
                        )}
                        {m.pricing_output && (
                            <span className="badge" style={{ background: 'var(--bg-glass)' }}>
                                OUT: {m.pricing_output}
                            </span>
                        )}
                    </div>
                )}

                                {/* Ollama specific size metadata */}
                {typeof m.size_gb === "number" && (
                    <div className="model-detail" style={{ marginTop: '6px' }}>
                        <strong>Disk Size:</strong> {m.size_gb.toFixed(1)} GB
                    </div>
                )}
                {m.parameter_size && (
                    <div className="model-detail">
                        <strong>Parameters:</strong> {m.parameter_size}
                    </div>
                )}

                {/* API Key Status for remote models */}
                {!m.is_local && (
                    <div className="model-detail" style={{ marginTop: 8 }}>
                        {m.api_key_set ? (
                            <span className="badge badge-success" style={{ background: 'transparent', padding: 0 }}>✅ API Key Configured</span>
                        ) : (
                            <span className="badge badge-warning" style={{ background: 'transparent', padding: 0 }}>⚠️ Missing API Key</span>
                        )}
                    </div>
                )}

                {isSwitching && (
                    <div style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 6 }}>
                        <span className="spinner" />
                        <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
                            Switching...
                        </span>
                    </div>
                )}
            </div>
        );
    };

    return (
        <>
            <div className="page-header">
                <div>
                    <div className="page-title">Models</div>
                    <div className="page-subtitle">
                        Manage and switch between local and remote LLM models
                    </div>
                </div>
                <button
                    className="btn btn-secondary"
                    onClick={fetchModels}
                    disabled={loading}
                    id="models-refresh"
                >
                    {loading ? <span className="spinner" /> : "↻ Refresh"}
                </button>
            </div>

            <div className="page-body">
                {loading && models.length === 0 ? (
                    <div className="empty-state">
                        <span className="spinner" />
                        <div className="empty-state-title" style={{ marginTop: 16 }}>
                            Loading models...
                        </div>
                    </div>
                ) : models.length === 0 ? (
                    <div className="empty-state">
                        <div className="empty-state-icon">⚡</div>
                        <div className="empty-state-title">No Models Found</div>
                        <div className="empty-state-text">
                            Make sure Ollama is running and the API server is connected.
                        </div>
                    </div>
                ) : (
                    <>
                        {/* Active Model Banner */}
                        <div
                            className="card"
                            style={{ marginBottom: 20, borderColor: "var(--accent-primary)" }}
                        >
                            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                                <span style={{ fontSize: 24 }}>⚡</span>
                                <div>
                                    <div
                                        style={{
                                            fontWeight: 600,
                                            fontSize: 14,
                                            color: "var(--text-primary)",
                                        }}
                                    >
                                        Active Model
                                    </div>
                                    <div style={{ fontSize: 13, color: "var(--accent-primary)" }}>
                                        {activeModelId || "None selected"}
                                    </div>
                                </div>
                            </div>
                        </div>

                        {/* Local Models */}
                        {localModels.length > 0 && (
                            <>
                                <h3
                                    style={{
                                        fontSize: 13,
                                        fontWeight: 600,
                                        color: "var(--text-muted)",
                                        textTransform: "uppercase",
                                        letterSpacing: 0.5,
                                        marginBottom: 12,
                                    }}
                                >
                                    🖥️ Local Models (Ollama)
                                </h3>
                                <div className="models-grid" style={{ marginBottom: 24 }}>
                                    {localModels.map(renderModelCard)}
                                </div>
                            </>
                        )}

                        {/* Gemini Models */}
                        {geminiModels.length > 0 && (
                            <>
                                <h3
                                    style={{
                                        fontSize: 13,
                                        fontWeight: 600,
                                        color: "var(--text-muted)",
                                        textTransform: "uppercase",
                                        letterSpacing: 0.5,
                                        marginBottom: 12,
                                    }}
                                >
                                    ☁️ Gemini Models
                                </h3>
                                <div className="models-grid" style={{ marginBottom: 24 }}>
                                    {geminiModels.map(renderModelCard)}
                                </div>
                            </>
                        )}

                        {/* Other Remote Models */}
                        {otherRemote.length > 0 && (
                            <>
                                <h3
                                    style={{
                                        fontSize: 13,
                                        fontWeight: 600,
                                        color: "var(--text-muted)",
                                        textTransform: "uppercase",
                                        letterSpacing: 0.5,
                                        marginBottom: 12,
                                    }}
                                >
                                    🌐 Other Remote Models
                                </h3>
                                <div className="models-grid">
                                    {otherRemote.map(renderModelCard)}
                                </div>
                            </>
                        )}
                    </>
                )}
            </div>
        </>
    );
}


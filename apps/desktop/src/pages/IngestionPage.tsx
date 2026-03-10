import { useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { ingestDocument, type IngestReport } from "../lib/api";

export default function IngestionPage() {
    const [path, setPath] = useState("");
    const [recursive, setRecursive] = useState(true);
    const [loading, setLoading] = useState(false);
    const [report, setReport] = useState<IngestReport | null>(null);
    const [error, setError] = useState<string | null>(null);

    const handleBrowseFile = async () => {
        try {
            const selected = await open({
                multiple: false,
                directory: false,
                title: "Select a file to ingest",
                filters: [
                    {
                        name: "Supported Files",
                        extensions: ["md", "txt", "py", "js", "ts", "tsx", "jsx", "json", "yaml", "yml", "toml", "cfg", "ini", "csv", "html", "css", "xml", "pdf", "rs", "go", "java", "c", "cpp", "h", "hpp", "rb", "php", "sh", "bat", "ps1"],
                    },
                    { name: "All Files", extensions: ["*"] },
                ],
            });
            if (selected) {
                setPath(selected);
            }
        } catch (err) {
            console.error("File dialog error:", err);
        }
    };

    const handleBrowseFolder = async () => {
        try {
            const selected = await open({
                multiple: false,
                directory: true,
                title: "Select a folder to ingest",
            });
            if (selected) {
                setPath(selected);
            }
        } catch (err) {
            console.error("Folder dialog error:", err);
        }
    };

    const handleIngest = async () => {
        const targetPath = path.trim();
        if (!targetPath || loading) return;

        setLoading(true);
        setReport(null);
        setError(null);

        try {
            const res = await ingestDocument(targetPath, recursive);
            setReport(res.report);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Ingestion failed");
        } finally {
            setLoading(false);
        }
    };

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            handleIngest();
        }
    };

    return (
        <>
            <div className="page-header">
                <div>
                    <div className="page-title">Ingestion</div>
                    <div className="page-subtitle">
                        Add files or directories to your vector database to inform Smart Chat responses
                    </div>
                </div>
            </div>

            <div className="page-body">
                <div className="card" style={{ marginBottom: 20 }}>
                    <div className="card-title">Ingest Documents</div>
                    <div className="card-subtitle" style={{ marginBottom: 12 }}>
                        Browse for a file or folder, or type an absolute path directly.
                    </div>

                    {/* Browse Buttons */}
                    <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
                        <button
                            className="btn btn-secondary"
                            onClick={handleBrowseFile}
                            disabled={loading}
                            id="ingest-browse-file"
                        >
                            📄 Browse File
                        </button>
                        <button
                            className="btn btn-secondary"
                            onClick={handleBrowseFolder}
                            disabled={loading}
                            id="ingest-browse-folder"
                        >
                            📁 Browse Folder
                        </button>
                    </div>

                    {/* Path Input + Ingest */}
                    <div className="input-group" style={{ marginBottom: 16 }}>
                        <input
                            className="input"
                            placeholder="C:\path\to\your\file_or_directory..."
                            value={path}
                            onChange={(e) => setPath(e.target.value)}
                            onKeyDown={handleKeyDown}
                            disabled={loading}
                            id="ingest-path"
                        />
                        <button
                            className="btn btn-primary"
                            onClick={handleIngest}
                            disabled={loading || !path.trim()}
                            id="ingest-run"
                        >
                            {loading ? (
                                <>
                                    <span className="spinner" /> Ingesting...
                                </>
                            ) : (
                                "📥 Ingest"
                            )}
                        </button>
                    </div>

                    <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                        <label className="toggle-switch" title="Process directories recursively">
                            <input
                                type="checkbox"
                                checked={recursive}
                                onChange={(e) => setRecursive(e.target.checked)}
                                disabled={loading}
                            />
                            <span className="toggle-slider" />
                        </label>
                        <label style={{ cursor: "pointer", fontSize: 13, color: "var(--text-secondary)" }}>
                            Recursive (for directories)
                        </label>
                    </div>
                </div>

                {error && (
                    <div className="card" style={{ borderLeft: "4px solid var(--error)", marginBottom: 20 }}>
                        <h4 style={{ margin: "0 0 8px 0", color: "var(--error)" }}>Error</h4>
                        <div style={{ color: "var(--text-muted)", fontSize: 13, wordWrap: "break-word" }}>{error}</div>
                    </div>
                )}

                {report && (
                    <div className="card" style={{ borderLeft: "4px solid var(--success)", marginBottom: 20 }}>
                        <h4 style={{ margin: "0 0 12px 0", color: "var(--success)" }}>Ingestion Complete</h4>

                        <div className="stats-row" style={{ marginTop: 0 }}>
                            <div className="stat-card" style={{ background: "var(--bg-primary)" }}>
                                <div className="stat-value">{report.processed_files}</div>
                                <div className="stat-label">Files Processed</div>
                            </div>
                            <div className="stat-card" style={{ background: "var(--bg-primary)" }}>
                                <div className="stat-value">{report.total_chunks}</div>
                                <div className="stat-label">Chunks Indexed</div>
                            </div>
                        </div>

                        {report.errors && Array.isArray(report.errors) && report.errors.length > 0 && (
                            <div style={{ marginTop: 16 }}>
                                <h5 style={{ margin: "0 0 8px 0", color: "var(--error)", fontSize: 12 }}>Skipped / Errors:</h5>
                                <ul style={{ margin: 0, paddingLeft: 20, fontSize: 12, color: "var(--text-muted)", wordWrap: "break-word" }}>
                                    {report.errors.map((err: any, i) => (
                                        <li key={i}>
                                            <strong>{err.file || "Unknown file"}</strong>: {err.error || JSON.stringify(err)}
                                        </li>
                                    ))}
                                </ul>
                            </div>
                        )}
                    </div>
                )}

                {/* Empty State */}
                {!report && !error && !loading && (
                    <div className="empty-state">
                        <div className="empty-state-icon">📥</div>
                        <div className="empty-state-title">Ready to Ingest</div>
                        <div className="empty-state-text">
                            Use the <strong>Browse</strong> buttons above to pick a file or folder from your computer,
                            or type a path directly. Supported formats: Markdown, Python, JS/TS, PDF, YAML, JSON, and more.
                        </div>
                    </div>
                )}
            </div>
        </>
    );
}



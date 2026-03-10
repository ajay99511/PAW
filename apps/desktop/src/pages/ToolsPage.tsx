import { useState } from "react";
import {
    toolListDir,
    toolReadFile,
    toolSearchFiles,
    toolRepoSummary,
    toolExecCommand,
    toolCheckCommand,
    listTools,
    type DirEntry,
    type DirListResult,
    type FileResult,
    type RepoSummaryResult,
    type CommandResult,
    type CommandCheckResult,
    type ToolInfo,
} from "../lib/api";

type ToolTab = "files" | "git" | "exec" | "registry";

export default function ToolsPage() {
    const [activeTab, setActiveTab] = useState<ToolTab>("files");

    return (
        <>
            <div className="page-header">
                <div>
                    <div className="page-title">Tools</div>
                    <div className="page-subtitle">
                        Local operations — browse files, analyze repos, and run commands
                    </div>
                </div>
            </div>

            <div className="page-body">
                {/* Tab Switcher */}
                <div className="tools-tabs" style={{ display: "flex", gap: 4, marginBottom: 20 }}>
                    {([
                        { id: "files" as ToolTab, label: "📂 Files", },
                        { id: "git" as ToolTab, label: "🔀 Git" },
                        { id: "exec" as ToolTab, label: "⚡ Execute" },
                        { id: "registry" as ToolTab, label: "🧩 Registry" },
                    ]).map((tab) => (
                        <button
                            key={tab.id}
                            className={`btn ${activeTab === tab.id ? "btn-primary" : "btn-secondary"}`}
                            onClick={() => setActiveTab(tab.id)}
                            id={`tools-tab-${tab.id}`}
                        >
                            {tab.label}
                        </button>
                    ))}
                </div>

                {activeTab === "files" && <FileBrowserPanel />}
                {activeTab === "git" && <GitPanel />}
                {activeTab === "exec" && <ExecPanel />}
                {activeTab === "registry" && <RegistryPanel />}
            </div>
        </>
    );
}


// ── File Browser Panel ─────────────────────────────────────────────

function FileBrowserPanel() {
    const [path, setPath] = useState("C:\\Agents\\PersonalAssist");
    const [dirResult, setDirResult] = useState<DirListResult | null>(null);
    const [fileContent, setFileContent] = useState<FileResult | null>(null);
    const [searchPattern, setSearchPattern] = useState("");
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const handleBrowse = async () => {
        if (!path.trim()) return;
        setLoading(true);
        setError(null);
        setFileContent(null);
        try {
            const res = await toolListDir(path.trim());
            setDirResult(res);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to list directory");
        } finally {
            setLoading(false);
        }
    };

    const handleClickItem = async (item: DirEntry) => {
        const newPath = `${path.replace(/[/\\]$/, "")}\\${item.name}`;
        if (item.type === "directory") {
            setPath(newPath);
            setLoading(true);
            setError(null);
            setFileContent(null);
            try {
                const res = await toolListDir(newPath);
                setDirResult(res);
            } catch (err) {
                setError(err instanceof Error ? err.message : "Failed to list directory");
            } finally {
                setLoading(false);
            }
        } else {
            // Read file
            setLoading(true);
            setError(null);
            try {
                const res = await toolReadFile(newPath, 200);
                setFileContent(res);
            } catch (err) {
                setError(err instanceof Error ? err.message : "Failed to read file");
            } finally {
                setLoading(false);
            }
        }
    };

    const handleSearch = async () => {
        if (!searchPattern.trim() || !path.trim()) return;
        setLoading(true);
        setError(null);
        setFileContent(null);
        try {
            const res = await toolSearchFiles(path.trim(), searchPattern.trim());
            // Convert search matches to a directory-like result for display
            setDirResult({
                path: `Search: ${searchPattern} in ${path}`,
                items: res.matches.map((m) => ({
                    name: m.name,
                    type: "file" as const,
                    size_bytes: m.size_bytes,
                    modified: m.modified,
                })),
                total_items: res.total_found,
            });
        } catch (err) {
            setError(err instanceof Error ? err.message : "Search failed");
        } finally {
            setLoading(false);
        }
    };

    const navigateUp = () => {
        const parts = path.replace(/[/\\]$/, "").split(/[/\\]/);
        if (parts.length > 1) {
            parts.pop();
            const newPath = parts.join("\\");
            setPath(newPath || "C:\\");
        }
    };

    const formatSize = (bytes?: number) => {
        if (bytes === undefined) return "";
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    };

    return (
        <>
            <div className="card" style={{ marginBottom: 16 }}>
                <div className="card-title">Browse Files</div>
                <div className="input-group" style={{ marginBottom: 8 }}>
                    <button className="btn btn-secondary btn-sm" onClick={navigateUp} title="Go up" id="fs-up">
                        ⬆️
                    </button>
                    <input
                        className="input"
                        value={path}
                        onChange={(e) => setPath(e.target.value)}
                        onKeyDown={(e) => e.key === "Enter" && handleBrowse()}
                        placeholder="Enter directory path..."
                        id="fs-path"
                    />
                    <button className="btn btn-primary" onClick={handleBrowse} disabled={loading} id="fs-browse">
                        {loading ? <span className="spinner" /> : "Browse"}
                    </button>
                </div>
                <div className="input-group">
                    <input
                        className="input"
                        value={searchPattern}
                        onChange={(e) => setSearchPattern(e.target.value)}
                        onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                        placeholder="Search pattern (e.g. *.py, *.md)"
                        id="fs-search"
                    />
                    <button className="btn btn-secondary" onClick={handleSearch} disabled={loading} id="fs-search-btn">
                        🔍 Search
                    </button>
                </div>
            </div>

            {error && (
                <div className="card" style={{ borderLeft: "4px solid var(--error)", marginBottom: 16 }}>
                    <div style={{ color: "var(--error)", fontSize: 13 }}>{error}</div>
                </div>
            )}

            {dirResult && (
                <div className="card" style={{ marginBottom: 16 }}>
                    <div className="card-subtitle" style={{ marginBottom: 8 }}>
                        📁 {dirResult.path} — {dirResult.total_items} items
                    </div>
                    <div className="tools-file-list">
                        {dirResult.items.map((item, i) => (
                            <div
                                key={i}
                                className="tools-file-item"
                                onClick={() => handleClickItem(item)}
                                style={{ cursor: "pointer" }}
                            >
                                <span className="tools-file-icon">
                                    {item.type === "directory" ? "📁" : "📄"}
                                </span>
                                <span className="tools-file-name">{item.name}</span>
                                <span className="tools-file-meta">
                                    {item.type === "directory"
                                        ? `${item.child_count ?? "?"} items`
                                        : formatSize(item.size_bytes)}
                                </span>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {fileContent && (
                <div className="card">
                    <div className="card-title" style={{ fontSize: 12 }}>
                        {fileContent.path}
                        {fileContent.truncated && (
                            <span className="badge badge-warning" style={{ marginLeft: 8 }}>Truncated</span>
                        )}
                    </div>
                    <div className="card-subtitle" style={{ marginBottom: 8 }}>
                        {fileContent.line_count} lines · {formatSize(fileContent.size_bytes)}
                    </div>
                    <pre className="tools-code-block">{fileContent.content}</pre>
                </div>
            )}

            {!dirResult && !fileContent && !error && !loading && (
                <div className="empty-state">
                    <div className="empty-state-icon">📂</div>
                    <div className="empty-state-title">File Browser</div>
                    <div className="empty-state-text">
                        Enter a directory path above and click Browse to explore your file system.
                    </div>
                </div>
            )}
        </>
    );
}


// ── Git Panel ──────────────────────────────────────────────────────

function GitPanel() {
    const [repoPath, setRepoPath] = useState("C:\\Agents\\PersonalAssist");
    const [summary, setSummary] = useState<RepoSummaryResult | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const handleAnalyze = async () => {
        if (!repoPath.trim()) return;
        setLoading(true);
        setError(null);
        try {
            const res = await toolRepoSummary(repoPath.trim());
            setSummary(res);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to analyze repo");
        } finally {
            setLoading(false);
        }
    };

    return (
        <>
            <div className="card" style={{ marginBottom: 16 }}>
                <div className="card-title">Repository Analysis</div>
                <div className="card-subtitle" style={{ marginBottom: 12 }}>
                    Enter a path to a git repository to get a summary of its status, branches, and recent commits.
                </div>
                <div className="input-group">
                    <input
                        className="input"
                        value={repoPath}
                        onChange={(e) => setRepoPath(e.target.value)}
                        onKeyDown={(e) => e.key === "Enter" && handleAnalyze()}
                        placeholder="C:\path\to\repo"
                        id="git-path"
                    />
                    <button className="btn btn-primary" onClick={handleAnalyze} disabled={loading} id="git-analyze">
                        {loading ? <><span className="spinner" /> Analyzing...</> : "🔀 Analyze"}
                    </button>
                </div>
            </div>

            {error && (
                <div className="card" style={{ borderLeft: "4px solid var(--error)", marginBottom: 16 }}>
                    <div style={{ color: "var(--error)", fontSize: 13 }}>{error}</div>
                </div>
            )}

            {summary && (
                <>
                    {/* Status Card */}
                    <div className="card" style={{ marginBottom: 16 }}>
                        <div className="card-title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                            Branch: {summary.status.branch}
                            <span className={`badge ${summary.status.clean ? "badge-success" : "badge-warning"}`}>
                                {summary.status.clean ? "Clean" : "Changes Detected"}
                            </span>
                        </div>

                        <div className="stats-row" style={{ marginTop: 12 }}>
                            <div className="stat-card" style={{ background: "var(--bg-primary)", padding: 12, borderRadius: "var(--radius-md)" }}>
                                <div className="stat-value">{summary.status.modified.length}</div>
                                <div className="stat-label">Modified</div>
                            </div>
                            <div className="stat-card" style={{ background: "var(--bg-primary)", padding: 12, borderRadius: "var(--radius-md)" }}>
                                <div className="stat-value">{summary.status.staged.length}</div>
                                <div className="stat-label">Staged</div>
                            </div>
                            <div className="stat-card" style={{ background: "var(--bg-primary)", padding: 12, borderRadius: "var(--radius-md)" }}>
                                <div className="stat-value">{summary.status.untracked.length}</div>
                                <div className="stat-label">Untracked</div>
                            </div>
                        </div>

                        {/* File lists */}
                        {summary.status.modified.length > 0 && (
                            <div style={{ marginTop: 12 }}>
                                <div style={{ fontSize: 12, fontWeight: 600, color: "var(--warning)", marginBottom: 4 }}>Modified:</div>
                                {summary.status.modified.map((f, i) => (
                                    <div key={i} style={{ fontSize: 12, color: "var(--text-secondary)", fontFamily: "var(--font-mono)", padding: "2px 0" }}>
                                        {f}
                                    </div>
                                ))}
                            </div>
                        )}
                        {summary.status.untracked.length > 0 && (
                            <div style={{ marginTop: 8 }}>
                                <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-muted)", marginBottom: 4 }}>Untracked:</div>
                                {summary.status.untracked.slice(0, 10).map((f, i) => (
                                    <div key={i} style={{ fontSize: 12, color: "var(--text-muted)", fontFamily: "var(--font-mono)", padding: "2px 0" }}>
                                        {f}
                                    </div>
                                ))}
                                {summary.status.untracked.length > 10 && (
                                    <div style={{ fontSize: 11, color: "var(--text-muted)", fontStyle: "italic" }}>
                                        ...and {summary.status.untracked.length - 10} more
                                    </div>
                                )}
                            </div>
                        )}
                    </div>

                    {/* Recent Commits */}
                    <div className="card" style={{ marginBottom: 16 }}>
                        <div className="card-title">Recent Commits</div>
                        <div className="tools-file-list" style={{ marginTop: 8 }}>
                            {summary.recent_commits.map((c, i) => (
                                <div key={i} className="tools-file-item">
                                    <span style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--accent-primary)", minWidth: 60 }}>
                                        {c.hash}
                                    </span>
                                    <span className="tools-file-name">{c.message}</span>
                                </div>
                            ))}
                        </div>
                    </div>

                    {/* Branches */}
                    <div className="card">
                        <div className="card-title">Branches</div>
                        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
                            {summary.branches.local.map((b, i) => (
                                <span
                                    key={i}
                                    className={`badge ${b === summary.branches.current ? "badge-accent" : "badge-info"}`}
                                >
                                    {b === summary.branches.current ? "★ " : ""}{b}
                                </span>
                            ))}
                        </div>
                    </div>
                </>
            )}

            {!summary && !error && !loading && (
                <div className="empty-state">
                    <div className="empty-state-icon">🔀</div>
                    <div className="empty-state-title">Repository Analysis</div>
                    <div className="empty-state-text">
                        Analyze a git repository to see its status, recent commits, and branch information.
                    </div>
                </div>
            )}
        </>
    );
}


// ── Exec Panel ─────────────────────────────────────────────────────

function ExecPanel() {
    const [command, setCommand] = useState("");
    const [cwd, setCwd] = useState("C:\\Agents\\PersonalAssist");
    const [result, setResult] = useState<CommandResult | null>(null);
    const [checkResult, setCheckResult] = useState<CommandCheckResult | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [history, setHistory] = useState<Array<{ command: string; result: CommandResult }>>([]);

    const handleCheck = async () => {
        if (!command.trim()) return;
        try {
            const res = await toolCheckCommand(command.trim());
            setCheckResult(res);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Check failed");
        }
    };

    const handleRun = async () => {
        if (!command.trim() || loading) return;
        setLoading(true);
        setError(null);
        setResult(null);
        setCheckResult(null);
        try {
            const res = await toolExecCommand(
                command.trim(),
                cwd.trim() || undefined,
                30,
            );
            setResult(res);
            setHistory((prev) => [{ command: command.trim(), result: res }, ...prev.slice(0, 9)]);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Execution failed");
        } finally {
            setLoading(false);
        }
    };

    return (
        <>
            <div className="card" style={{ marginBottom: 16 }}>
                <div className="card-title">Command Execution</div>
                <div className="card-subtitle" style={{ marginBottom: 12 }}>
                    Run shell commands in a sandboxed subprocess. Pre-approved commands run instantly;
                    others require your explicit approval.
                </div>

                <div style={{ marginBottom: 8 }}>
                    <label style={{ fontSize: 12, color: "var(--text-muted)" }}>Working Directory</label>
                    <input
                        className="input"
                        value={cwd}
                        onChange={(e) => setCwd(e.target.value)}
                        placeholder="Working directory (optional)"
                        style={{ marginTop: 4 }}
                        id="exec-cwd"
                    />
                </div>

                <div className="input-group" style={{ marginBottom: 8 }}>
                    <input
                        className="input"
                        value={command}
                        onChange={(e) => { setCommand(e.target.value); setCheckResult(null); }}
                        onKeyDown={(e) => e.key === "Enter" && handleRun()}
                        onBlur={handleCheck}
                        placeholder="git status, npm run build, python --version..."
                        id="exec-command"
                    />
                    <button
                        className="btn btn-primary"
                        onClick={() => handleRun()}
                        disabled={loading || !command.trim()}
                        id="exec-run"
                    >
                        {loading ? <><span className="spinner" /> Running...</> : "▶ Run"}
                    </button>
                </div>

                {/* Safety indicator */}
                {checkResult && (
                    <div style={{ fontSize: 12, display: "flex", alignItems: "center", gap: 6, marginTop: 4 }}>
                        {checkResult.allowed && (
                            <span className="badge badge-success">✅ Pre-approved</span>
                        )}
                        {checkResult.blocked && (
                            <span className="badge" style={{ background: "rgba(248,113,113,0.15)", color: "var(--error)" }}>
                                ⛔ Blocked — this command is not allowed
                            </span>
                        )}
                        {checkResult.requires_approval && (
                            <span className="badge badge-warning">
                                ⚠️ Manual approval required (not available in this panel)
                            </span>
                        )}
                    </div>
                )}
            </div>

            {error && (
                <div className="card" style={{ borderLeft: "4px solid var(--error)", marginBottom: 16 }}>
                    <div style={{ color: "var(--error)", fontSize: 13 }}>{error}</div>
                </div>
            )}

            {/* Current result */}
            {result && (
                <div className="card" style={{
                    borderLeft: `4px solid ${result.success ? "var(--success)" : result.status === "pending_approval" ? "var(--warning)" : "var(--error)"}`,
                    marginBottom: 16,
                }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                        <span className={`badge ${result.success ? "badge-success" : result.status === "pending_approval" ? "badge-warning" : ""}`}
                            style={!result.success && result.status !== "pending_approval" ? { background: "rgba(248,113,113,0.15)", color: "var(--error)" } : {}}
                        >
                            {result.success ? "✅ Success" : result.status === "pending_approval" ? "⚠️ Needs Approval" : `❌ Exit code ${result.returncode}`}
                        </span>
                        <span style={{ fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>
                            {result.command}
                        </span>
                    </div>

                    {result.status === "pending_approval" && (
                        <div style={{ marginBottom: 8, fontSize: 13, color: "var(--text-secondary)" }}>
                            {result.message} This UI currently supports pre-approved commands only.
                        </div>
                    )}

                    {result.stdout && (
                        <pre className="tools-code-block">{result.stdout}</pre>
                    )}
                    {result.stderr && (
                        <pre className="tools-code-block" style={{ borderLeftColor: "var(--error)" }}>
                            {result.stderr}
                        </pre>
                    )}
                </div>
            )}

            {/* Command History */}
            {history.length > 0 && (
                <div className="card">
                    <div className="card-title">Recent Commands</div>
                    <div className="tools-file-list" style={{ marginTop: 8 }}>
                        {history.map((h, i) => (
                            <div
                                key={i}
                                className="tools-file-item"
                                style={{ cursor: "pointer" }}
                                onClick={() => setCommand(h.command)}
                            >
                                <span style={{ fontSize: 14 }}>
                                    {h.result.success ? "✅" : "❌"}
                                </span>
                                <span className="tools-file-name" style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>
                                    {h.command}
                                </span>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {!result && history.length === 0 && !error && !loading && (
                <div className="empty-state">
                    <div className="empty-state-icon">⚡</div>
                    <div className="empty-state-title">Command Runner</div>
                    <div className="empty-state-text">
                        Type a shell command above and press Run. Pre-approved commands
                        (git status, npm run build, etc.) execute instantly.
                    </div>
                </div>
            )}
        </>
    );
}


// ── Registry Panel ─────────────────────────────────────────────────

function RegistryPanel() {
    const [tools, setTools] = useState<ToolInfo[]>([]);
    const [loading, setLoading] = useState(false);

    const handleLoad = async () => {
        setLoading(true);
        try {
            const res = await listTools();
            setTools(res.tools);
        } catch {
            // silently fail
        } finally {
            setLoading(false);
        }
    };

    const categories = [...new Set(tools.map((t) => t.category))];
    const getCategoryIcon = (cat: string) => {
        switch (cat) {
            case "memory": return "🧠";
            case "filesystem": return "📂";
            case "git": return "🔀";
            case "execution": return "⚡";
            default: return "🧩";
        }
    };

    return (
        <>
            <div className="card" style={{ marginBottom: 16 }}>
                <div className="card-title">Agent Tool Registry</div>
                <div className="card-subtitle" style={{ marginBottom: 12 }}>
                    All tools available to the agent orchestrator. These are callable by the Planner, Researcher, and Synthesizer agents.
                </div>
                <button className="btn btn-primary" onClick={handleLoad} disabled={loading} id="registry-load">
                    {loading ? <><span className="spinner" /> Loading...</> : "🔄 Load Tools"}
                </button>
            </div>

            {tools.length > 0 && categories.map((cat) => (
                <div key={cat} className="card" style={{ marginBottom: 12 }}>
                    <div className="card-title" style={{ textTransform: "capitalize" }}>
                        {getCategoryIcon(cat)} {cat}
                    </div>
                    <div className="tools-file-list" style={{ marginTop: 8 }}>
                        {tools
                            .filter((t) => t.category === cat)
                            .map((t, i) => (
                                <div key={i} className="tools-file-item">
                                    <span className="tools-file-name" style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--accent-primary)" }}>
                                        {t.name}
                                    </span>
                                    <span className="tools-file-meta" style={{ flex: 1, textAlign: "left", marginLeft: 12 }}>
                                        {t.description}
                                    </span>
                                </div>
                            ))}
                    </div>
                </div>
            ))}

            {tools.length === 0 && !loading && (
                <div className="empty-state">
                    <div className="empty-state-icon">🧩</div>
                    <div className="empty-state-title">Tool Registry</div>
                    <div className="empty-state-text">
                        Click "Load Tools" to see all tools available to the agent system.
                    </div>
                </div>
            )}
        </>
    );
}


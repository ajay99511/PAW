import { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
    chatSmart,
    chatPlain,
    chatStream,
    listModels,
    getActiveModel,
    getActiveContext,
    clearActiveContext,
    getChatThreads,
    getChatThread,
    deleteChatThread,
    type ChatThread,
    type ChatResponse,
    type ModelInfo,
} from "../lib/api";

interface Message {
    id?: string;
    role: "user" | "assistant";
    content: string;
    model?: string;
    memoryUsed?: boolean;
    timestamp: Date;
}

export default function ChatPage() {
    const [messages, setMessages] = useState<Message[]>([]);
    const [input, setInput] = useState("");
    const [loading, setLoading] = useState(false);
    const [smartMode, setSmartMode] = useState(true);
    const [streamMode, setStreamMode] = useState(false);

    // Model state
    const [availableModels, setAvailableModels] = useState<ModelInfo[]>([]);
    const [selectedModelId, setSelectedModelId] = useState("");
    const [isFetchingModels, setIsFetchingModels] = useState(false);

    // Active Context state
    const [activeContext, setActiveContext] = useState<any>(null);

    // Thread state
    const [threads, setThreads] = useState<ChatThread[]>([]);
    const [currentThreadId, setCurrentThreadId] = useState<string | null>(null);
    const [isSidebarOpen, setIsSidebarOpen] = useState(true);

    const messagesEndRef = useRef<HTMLDivElement>(null);
    const textareaRef = useRef<HTMLTextAreaElement>(null);

    // Initial fetch
    useEffect(() => {
        let mounted = true;
        const fetchInitialData = async () => {
            setIsFetchingModels(true);
            try {
                const [modelData, activeData, contextData, threadsData] = await Promise.all([
                    listModels(),
                    getActiveModel(),
                    getActiveContext(),
                    getChatThreads().catch(() => ({ threads: [] })) // Graceful fallback
                ]);
                if (mounted) {
                    setAvailableModels(modelData.models || []);
                    setSelectedModelId(activeData.active_model || "local");
                    if (Object.keys(contextData).length > 0) {
                        setActiveContext(contextData);
                    }
                    setThreads(threadsData.threads || []);
                }
            } catch (err) {
                console.error("Failed to fetch initial data for chat:", err);
            } finally {
                if (mounted) setIsFetchingModels(false);
            }
        };
        fetchInitialData();
        return () => { mounted = false; };
    }, []);

    // Refresh threads whenever a new message finishes
    const refreshThreads = async () => {
        try {
            const data = await getChatThreads();
            setThreads(data.threads || []);
        } catch (e) {
            console.error("Failed to refresh threads", e);
        }
    };

    // Load a specific thread
    const loadThread = async (threadId: string) => {
        if (loading) return;
        setLoading(true);
        try {
            const detail = await getChatThread(threadId);
            const mappedMessages: Message[] = detail.messages.map((m: any) => ({
                id: m.id,
                role: m.role,
                content: m.content,
                model: m.model_used,
                memoryUsed: m.memory_used,
                timestamp: new Date(m.timestamp)
            }));
            setMessages(mappedMessages);
            setCurrentThreadId(threadId);
        } catch (err) {
            console.error("Failed to load thread", err);
        } finally {
            setLoading(false);
        }
    };

    const handleDeleteThread = async (e: React.MouseEvent, threadId: string) => {
        e.stopPropagation();
        if (!confirm("Are you sure you want to delete this chat?")) return;

        try {
            await deleteChatThread(threadId);
            if (currentThreadId === threadId) {
                handleNewChat();
            }
            refreshThreads();
        } catch (err) {
            console.error("Failed to delete thread", err);
        }
    };

    const handleNewChat = () => {
        if (loading) return;
        setMessages([]);
        setCurrentThreadId(null);
    };

    // Auto-scroll
    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [messages]);

    // Auto-resize textarea
    useEffect(() => {
        if (textareaRef.current) {
            textareaRef.current.style.height = 'auto';
            const scrollHeight = textareaRef.current.scrollHeight;
            textareaRef.current.style.height = `${Math.min(scrollHeight, 150)}px`;
        }
    }, [input]);

    const handleSend = async () => {
        const text = input.trim();
        if (!text || loading) return;

        const userMsg: Message = {
            role: "user",
            content: text,
            timestamp: new Date(),
        };
        setMessages((prev) => [...prev, userMsg]);
        setInput("");
        setLoading(true);

        try {
            if (streamMode) {
                const streamingMsg: Message = {
                    role: "assistant",
                    content: "",
                    model: selectedModelId,
                    timestamp: new Date(),
                };
                setMessages((prev) => [...prev, streamingMsg]);

                let firstChunk = true;
                for await (const chunk of chatStream(text, selectedModelId, currentThreadId || undefined)) {
                    if (typeof chunk === 'object' && chunk !== null && 'thread_id' in chunk) {
                        if (!currentThreadId) setCurrentThreadId(chunk.thread_id);
                        continue;
                    }

                    if (typeof chunk === 'string') {
                        setMessages((prev) => {
                            const updated = [...prev];
                            const last = updated[updated.length - 1];
                            if (last.role === "assistant") {
                                updated[updated.length - 1] = {
                                    ...last,
                                    content: last.content + chunk,
                                };
                            }
                            return updated;
                        });

                        // Refresh threads after the first real text chunk yields
                        if (firstChunk) {
                            refreshThreads();
                            firstChunk = false;
                        }
                    }
                }
            } else {
                const fn = smartMode ? chatSmart : chatPlain;
                const resp: ChatResponse = await fn(text, selectedModelId, currentThreadId || undefined);

                if (resp.thread_id && !currentThreadId) {
                    setCurrentThreadId(resp.thread_id);
                }

                const assistantMsg: Message = {
                    role: "assistant",
                    content: resp.response,
                    model: resp.model_used,
                    memoryUsed: resp.memory_used,
                    timestamp: new Date(),
                };
                setMessages((prev) => [...prev, assistantMsg]);
                refreshThreads();
            }
        } catch (err) {
            const errorMsg: Message = {
                role: "assistant",
                content: `⚠️ Error: ${err instanceof Error ? err.message : "Failed to get response"}`,
                timestamp: new Date(),
            };
            setMessages((prev) => [...prev, errorMsg]);
        } finally {
            setLoading(false);
        }
    };

    const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    };

    const copyToClipboard = async (text: string) => {
        try {
            await navigator.clipboard.writeText(text);
        } catch (err) {
            console.error('Failed to copy text: ', err);
        }
    };

    // Group models for the dropdown
    const localModels = availableModels.filter(m => m.is_local);
    const geminiModels = availableModels.filter(m => !m.is_local && m.provider === 'gemini');
    const otherRemote = availableModels.filter(m => !m.is_local && m.provider !== 'gemini');

    return (
        <div style={{ display: 'flex', height: '100%', width: '100%', overflow: 'hidden' }}>
            {/* Sidebar */}
            {isSidebarOpen && (
                <div style={{
                    width: 260,
                    borderRight: '1px solid var(--border)',
                    background: 'var(--bg-secondary)',
                    display: 'flex',
                    flexDirection: 'column',
                    flexShrink: 0
                }}>
                    <div style={{ padding: '16px' }}>
                        <button
                            className="btn btn-primary"
                            style={{ width: '100%', display: 'flex', justifyContent: 'center', gap: '8px' }}
                            onClick={handleNewChat}
                            disabled={loading}
                        >
                            <span>🆕</span> New Chat
                        </button>
                    </div>

                    <div style={{ flex: 1, overflowY: 'auto', padding: '0 8px 16px 8px' }}>
                        <div style={{ fontSize: '11px', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 600, padding: '8px' }}>
                            Recent Chats
                        </div>
                        {threads.length === 0 && (
                            <div style={{ padding: '8px', fontSize: '13px', color: 'var(--text-muted)', textAlign: 'center' }}>
                                No history yet
                            </div>
                        )}
                        {threads.map(t => (
                            <div
                                key={t.id}
                                onClick={() => loadThread(t.id)}
                                style={{
                                    padding: '10px 12px',
                                    borderRadius: '8px',
                                    cursor: 'pointer',
                                    display: 'flex',
                                    justifyContent: 'space-between',
                                    alignItems: 'center',
                                    background: currentThreadId === t.id ? 'var(--bg-hover)' : 'transparent',
                                    color: currentThreadId === t.id ? 'var(--text)' : 'var(--text-muted)',
                                    marginBottom: '4px',
                                    fontSize: '14px',
                                    transition: 'background 0.2s ease'
                                }}
                                title={t.title}
                            >
                                <span style={{
                                    whiteSpace: 'nowrap',
                                    overflow: 'hidden',
                                    textOverflow: 'ellipsis',
                                    flex: 1
                                }}>
                                    {t.title}
                                </span>
                                <button
                                    onClick={(e) => handleDeleteThread(e, t.id)}
                                    style={{
                                        background: 'transparent',
                                        border: 'none',
                                        color: 'inherit',
                                        opacity: currentThreadId === t.id ? 0.7 : 0,
                                        cursor: 'pointer',
                                        padding: '4px'
                                    }}
                                    title="Delete Chat"
                                >
                                    ✕
                                </button>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Main Chat Area */}
            <div className="chat-container" style={{ flex: 1, border: 'none', borderRadius: 0, height: '100%' }}>
                <div style={{
                    padding: '12px 16px',
                    borderBottom: '1px solid var(--border)',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    background: 'var(--bg-secondary)'
                }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                        <button
                            onClick={() => setIsSidebarOpen(!isSidebarOpen)}
                            style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--text)', fontSize: 18 }}
                            title="Toggle Sidebar"
                        >
                            ☰
                        </button>
                        <div style={{ fontSize: 16, fontWeight: 600 }}>
                            {currentThreadId ? threads.find(t => t.id === currentThreadId)?.title || "Chat Session" : "New Chat"}
                        </div>
                    </div>
                </div>

                {/* Messages Area */}
                <div className="chat-messages" style={{ flex: 1 }}>
                    {messages.length === 0 && (
                        <div className="empty-state">
                            <div className="empty-state-icon">💬</div>
                            <div className="empty-state-title">Start a Conversation</div>
                            <div className="empty-state-text">
                                Ask anything — PersonalAssist uses your memories and documents for
                                context-aware responses.
                            </div>
                        </div>
                    )}

                    {messages.map((msg, i) => (
                        <div key={i} className={`message ${msg.role}`}>
                            {msg.role === "assistant" ? (
                                <div className="markdown-body">
                                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                        {msg.content}
                                    </ReactMarkdown>
                                </div>
                            ) : (
                                <div>{msg.content}</div>
                            )}
                            <div className="message-meta" style={{ justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start' }}>
                                {msg.role === "assistant" && msg.model && (
                                    <span className="badge badge-accent">{msg.model}</span>
                                )}
                                {msg.memoryUsed && (
                                    <span className="badge badge-success">🧠 Memory</span>
                                )}
                                <span>
                                    {msg.timestamp.toLocaleTimeString([], {
                                        hour: "2-digit",
                                        minute: "2-digit",
                                    })}
                                </span>
                                {msg.role === "assistant" && (
                                    <button
                                        onClick={() => copyToClipboard(msg.content)}
                                        style={{
                                            background: 'transparent', border: 'none', color: 'inherit',
                                            cursor: 'pointer', padding: '0 4px', fontSize: 14,
                                            opacity: 0.7, transform: 'translateY(-1px)'
                                        }}
                                        title="Copy response"
                                    >
                                        📋
                                    </button>
                                )}
                            </div>
                        </div>
                    ))}

                    {loading && !streamMode && (
                        <div className="typing-indicator">
                            <span /><span /><span />
                        </div>
                    )}
                    <div ref={messagesEndRef} />
                </div>

                {/* Active Context Banner */}
                {activeContext && (
                    <div style={{
                        margin: '8px 16px',
                        padding: '8px 12px',
                        background: 'rgba(79, 172, 254, 0.1)',
                        border: '1px solid rgba(79, 172, 254, 0.3)',
                        borderRadius: '8px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        fontSize: '13px'
                    }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <span style={{ color: 'var(--accent-color)' }}>◉ Active Context Detected</span>
                            <span style={{ color: 'var(--text-muted)' }}>
                                {activeContext.file_path && `File: ${activeContext.file_path.split(/[/\\]/).pop()} `}
                                {activeContext.terminal_error && `(Terminal Error)`}
                            </span>
                        </div>
                        <button
                            onClick={async () => {
                                await clearActiveContext();
                                setActiveContext(null);
                            }}
                            style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '12px' }}
                        >
                            ✕ Clear
                        </button>
                    </div>
                )}

                {/* Input Bar */}
                <div className="chat-input-bar">
                    <div className="chat-controls">
                        <label className="toggle-switch" title="Smart Mode (RAG-enhanced)">
                            <input
                                type="checkbox"
                                checked={smartMode}
                                onChange={(e) => {
                                    setSmartMode(e.target.checked);
                                    if (e.target.checked) setStreamMode(false);
                                }}
                            />
                            <span className="toggle-slider" />
                        </label>
                        <label style={{ cursor: "pointer" }}>Smart</label>

                        <div style={{ width: 1, height: 16, background: "var(--border)", margin: "0 4px" }} />

                        <label className="toggle-switch" title="Streaming Mode">
                            <input
                                type="checkbox"
                                checked={streamMode}
                                onChange={(e) => {
                                    setStreamMode(e.target.checked);
                                    if (e.target.checked) setSmartMode(false);
                                }}
                            />
                            <span className="toggle-slider" />
                        </label>
                        <label style={{ cursor: "pointer" }}>Stream</label>

                        <div style={{ flex: 1 }} />

                        {isFetchingModels ? (
                            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Loading models...</div>
                        ) : (
                            <select
                                className="input"
                                value={selectedModelId}
                                onChange={(e) => setSelectedModelId(e.target.value)}
                                style={{ width: 'auto', minWidth: 180, flex: "none", padding: '6px 28px 6px 10px' }}
                            >
                                {localModels.length > 0 && (
                                    <optgroup label="🖥️ Local Models">
                                        {localModels.map(m => (
                                            <option key={m.id} value={m.id}>{m.name || m.id}</option>
                                        ))}
                                    </optgroup>
                                )}
                                {geminiModels.length > 0 && (
                                    <optgroup label="☁️ Gemini Models">
                                        {geminiModels.map(m => (
                                            <option key={m.id} value={m.id}>{m.name || m.id}</option>
                                        ))}
                                    </optgroup>
                                )}
                                {otherRemote.length > 0 && (
                                    <optgroup label="🌐 Other Remote">
                                        {otherRemote.map(m => (
                                            <option key={m.id} value={m.id}>{m.name || m.id}</option>
                                        ))}
                                    </optgroup>
                                )}
                            </select>
                        )}
                    </div>

                    <div className="input-group" style={{ alignItems: 'flex-end', background: 'var(--bg-input)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border)', padding: '2px' }}>
                        <textarea
                            ref={textareaRef}
                            className="input"
                            placeholder="Type a message... (Shift+Enter for new line)"
                            value={input}
                            onChange={(e) => setInput(e.target.value)}
                            onKeyDown={handleKeyDown}
                            disabled={loading}
                            id="chat-input"
                            rows={1}
                            style={{
                                resize: 'none',
                                background: 'transparent',
                                border: 'none',
                                maxHeight: 150,
                                padding: '10px 14px',
                                minHeight: 40
                            }}
                        />
                        <button
                            className="btn btn-primary"
                            onClick={handleSend}
                            disabled={loading || !input.trim()}
                            id="chat-send"
                            style={{ margin: '6px' }}
                        >
                            {loading ? <span className="spinner" /> : "Send"}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}

import { useState, useRef, useEffect } from "react";
import { chatSmart, chatPlain, chatStream, type ChatResponse } from "../lib/api";

interface Message {
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
    const [model, setModel] = useState("local");
    const messagesEndRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [messages]);

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
                // SSE streaming mode
                const streamingMsg: Message = {
                    role: "assistant",
                    content: "",
                    model,
                    timestamp: new Date(),
                };
                setMessages((prev) => [...prev, streamingMsg]);

                for await (const chunk of chatStream(text, model)) {
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
                }
            } else {
                // Regular or Smart mode
                const fn = smartMode ? chatSmart : chatPlain;
                const resp: ChatResponse = await fn(text, model);
                const assistantMsg: Message = {
                    role: "assistant",
                    content: resp.response,
                    model: resp.model_used,
                    memoryUsed: resp.memory_used,
                    timestamp: new Date(),
                };
                setMessages((prev) => [...prev, assistantMsg]);
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

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    };

    return (
        <div className="chat-container">
            {/* Messages Area */}
            <div className="chat-messages">
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
                        <div>{msg.content}</div>
                        <div className="message-meta">
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
                    <label style={{ cursor: "pointer" }}>
                        Smart
                    </label>

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
                    <label style={{ cursor: "pointer" }}>
                        Stream
                    </label>

                    <div style={{ flex: 1 }} />

                    <select
                        className="input"
                        value={model}
                        onChange={(e) => setModel(e.target.value)}
                        style={{ width: 160, flex: "none" }}
                    >
                        <option value="local">Local (Ollama)</option>
                        <option value="gemini">Gemini Flash</option>
                        <option value="claude">Claude Sonnet</option>
                        <option value="active">Active Model</option>
                    </select>
                </div>

                <div className="input-group">
                    <input
                        className="input"
                        placeholder="Type a message..."
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={handleKeyDown}
                        disabled={loading}
                        id="chat-input"
                    />
                    <button
                        className="btn btn-primary"
                        onClick={handleSend}
                        disabled={loading || !input.trim()}
                        id="chat-send"
                    >
                        {loading ? <span className="spinner" /> : "Send"}
                    </button>
                </div>
            </div>
        </div>
    );
}

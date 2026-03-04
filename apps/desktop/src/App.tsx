import { useState, useEffect, useCallback, useRef } from "react";
import "./index.css";

import ChatPage from "./pages/ChatPage";
import MemoryPage from "./pages/MemoryPage";
import ModelsPage from "./pages/ModelsPage";
import AgentsPage from "./pages/AgentsPage";
import { checkHealth } from "./lib/api";

type Page = "chat" | "memory" | "models" | "agents";

const NAV_ITEMS: { id: Page; label: string; icon: string }[] = [
  { id: "chat", label: "Chat", icon: "💬" },
  { id: "memory", label: "Memory", icon: "🧠" },
  { id: "models", label: "Models", icon: "⚡" },
  { id: "agents", label: "Agents", icon: "🤖" },
];

function App() {
  const [activePage, setActivePage] = useState<Page>("chat");
  const [apiOnline, setApiOnline] = useState(false);
  const healthRef = useRef<ReturnType<typeof setInterval>>(undefined);

  const pollHealth = useCallback(async () => {
    try {
      await checkHealth();
      setApiOnline(true);
    } catch {
      setApiOnline(false);
    }
  }, []);

  useEffect(() => {
    pollHealth();
    healthRef.current = setInterval(pollHealth, 10000);
    return () => clearInterval(healthRef.current);
  }, [pollHealth]);

  const renderPage = () => {
    switch (activePage) {
      case "chat":
        return <ChatPage />;
      case "memory":
        return <MemoryPage />;
      case "models":
        return <ModelsPage />;
      case "agents":
        return <AgentsPage />;
    }
  };

  return (
    <div className="app-layout">
      {/* ── Sidebar ── */}
      <aside className="sidebar">
        <div className="sidebar-brand">
          <div className="sidebar-brand-icon">P</div>
          <div>
            <div className="sidebar-brand-text">PersonalAssist</div>
          </div>
          <span className="sidebar-brand-version">v0.2</span>
        </div>

        <nav>
          {NAV_ITEMS.map((item) => (
            <div
              key={item.id}
              className={`nav-item ${activePage === item.id ? "active" : ""}`}
              onClick={() => setActivePage(item.id)}
            >
              <span className="nav-icon">{item.icon}</span>
              {item.label}
            </div>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="nav-item" style={{ cursor: "default" }}>
            <span
              className={`status-dot ${apiOnline ? "online" : "offline"}`}
            />
            <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
              API {apiOnline ? "Connected" : "Offline"}
            </span>
          </div>
        </div>
      </aside>

      {/* ── Main Content ── */}
      <main className="main-content">{renderPage()}</main>
    </div>
  );
}

export default App;

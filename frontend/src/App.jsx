import React, { useState, useRef, useEffect } from "react";
import { api } from "./api.js";
import Sidebar from "./components/Sidebar.jsx";
import StatusPanel from "./components/StatusPanel.jsx";
import TabPicker from "./components/TabPicker.jsx";
import PinPrompt from "./components/PinPrompt.jsx";

const STARTER_SUGGESTIONS = [
  "Save this project",
  "What did I work on today?",
  "Resume my last project",
  "Find file report.docx",
];

function Message({ role, text }) {
  return (
    <div className={`msg-row ${role}`}>
      <div className="bubble" dangerouslySetInnerHTML={{ __html: formatText(text) }} />
    </div>
  );
}

function formatText(text) {
  const escaped = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  return escaped
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`(.+?)`/g, "<code>$1</code>")
    .replace(/\n/g, "<br/>");
}

export default function App() {
  const [messages, setMessages] = useState([
    {
      role: "assistant",
      text:
        "Hi — I'm your Project Context Manager and OS assistant. Save a project folder, resume one from the sidebar, or ask me anything about your files and system.",
    },
  ]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [activeProject, setActiveProject] = useState(null);
  const [sidebarRefresh, setSidebarRefresh] = useState(0);
  const [awaiting, setAwaiting] = useState(null);
  const [pendingContext, setPendingContext] = useState(null);
  const [unlocked, setUnlocked] = useState(false);
  const scrollRef = useRef(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  const send = async (text, hidden) => {
    const trimmed = (text ?? input).trim();
    if (!trimmed || busy) return;

    if (!hidden) {
      setMessages((m) => [...m, { role: "user", text: trimmed }]);
    }
    setInput("");
    setBusy(true);

    try {
      const res = await api.chat(trimmed, activeProject?.id, awaiting, pendingContext, unlocked);
      setMessages((m) => [...m, { role: "assistant", text: res.reply }]);
      if (res.active_project_id) {
        setActiveProject({ id: res.active_project_id, path: res.active_project_path });
      }
      setAwaiting(res.awaiting || null);
      setPendingContext(res.awaiting ? res.data || null : null);
      if (res.unlocked) setUnlocked(true);
      setSidebarRefresh((n) => n + 1);
    } catch (e) {
      setMessages((m) => [...m, { role: "assistant", text: `Something went wrong: ${e.message}` }]);
    } finally {
      setBusy(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  const handleClearMemory = async () => {
    if (!window.confirm("Delete everything I've saved about your projects? This can't be undone.")) return;
    await api.deleteAllData();
    setActiveProject(null);
    setSidebarRefresh((n) => n + 1);
    setMessages((m) => [...m, { role: "assistant", text: "Done — I've cleared everything I had saved." }]);
  };

  const handleSidebarResume = (project) => {
    setActiveProject({ id: project.id, path: project.path });
    send(`resume ${project.name}`);
  };

  const showStarterChips = messages.length <= 1;

  return (
    <div className="shell">
      <Sidebar activeProjectId={activeProject?.id} onResume={handleSidebarResume} refreshKey={sidebarRefresh} />

      <div className="app">
        <header className="app-header">
          <div className="title-block">
            <h1>Project Context Manager</h1>
            <div className="subtitle">Everything stays local on this machine</div>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {activeProject?.path && (
              <div className="active-project" title={activeProject.path}>
                {activeProject.path.split(/[\\/]/).filter(Boolean).pop()}
              </div>
            )}
            <button className="icon-btn" onClick={handleClearMemory}>Clear memory</button>
          </div>
        </header>

        <div className="chat-scroll" ref={scrollRef}>
          {messages.map((m, i) => (
            <Message key={i} role={m.role} text={m.text} />
          ))}
          {busy && (
            <div className="msg-row assistant">
              <div className="bubble">
                <span className="typing-dots"><span></span><span></span><span></span></span>
              </div>
            </div>
          )}
        </div>

        {showStarterChips && (
          <div className="suggestions">
            {STARTER_SUGGESTIONS.map((s) => (
              <div key={s} className="suggestion-chip" onClick={() => send(s)}>{s}</div>
            ))}
          </div>
        )}

        {awaiting === "select_tabs" && pendingContext?.tabs && (
          <TabPicker
            tabs={pendingContext.tabs}
            disabled={busy}
            onConfirm={(selection) => send(selection)}
          />
        )}

        {awaiting === "enter_pin" && (
          <PinPrompt disabled={busy} onConfirm={(pin) => send(pin, true)} />
        )}

        <div className="composer">
          <textarea
            rows={1}
            placeholder="Ask me anything about your projects or this machine…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
          />
          <button className="send" onClick={() => send()} disabled={busy || !input.trim()}>↑</button>
        </div>
      </div>

      <StatusPanel activeProject={activeProject} />
    </div>
  );
}

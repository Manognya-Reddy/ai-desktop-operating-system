import React, { useEffect, useState } from "react";
import { api } from "../api.js";

export default function Sidebar({ activeProjectId, onResume, refreshKey }) {
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = () => {
    api.listProjects()
      .then((data) => setProjects(data))
      .catch(() => setProjects([]))
      .finally(() => setLoading(false));
  };

  useEffect(load, [refreshKey]);

  return (
    <aside className="sidebar">
      <div className="sidebar-heading">Saved Projects</div>
      <div className="sidebar-list">
        {loading && <div className="muted small">Loading…</div>}
        {!loading && projects.length === 0 && (
          <div className="muted small">Nothing saved yet. Tell the assistant to save a folder.</div>
        )}
        {projects.map((p) => (
          <div
            key={p.id}
            className={`sidebar-item ${p.id === activeProjectId ? "active" : ""}`}
            onClick={() => onResume(p)}
            title={p.path}
          >
            <div className="sidebar-item-name">{p.name}</div>
            <div className="sidebar-item-desc">{p.semantic_description || p.path}</div>
            <div className="sidebar-item-time">{new Date(p.updated_at).toLocaleDateString()}</div>
          </div>
        ))}
      </div>
    </aside>
  );
}

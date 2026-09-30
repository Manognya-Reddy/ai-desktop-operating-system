import React, { useEffect, useState } from "react";
import { api } from "../api.js";

export default function StatusPanel({ activeProject }) {
  const [status, setStatus] = useState(null);

  useEffect(() => {
    const load = () => api.systemStatus().then(setStatus).catch(() => {});
    load();
    const id = setInterval(load, 15000);
    return () => clearInterval(id);
  }, []);

  return (
    <aside className="status-panel">
      <div className="sidebar-heading">This Machine</div>

      {!status && <div className="muted small">Reading system status…</div>}

      {status && (
        <div className="status-block">
          <div className="status-row">
            <span>OS</span>
            <span>{status.system.os}</span>
          </div>
          {"cpu_percent" in status.system && (
            <>
              <div className="status-row">
                <span>CPU</span>
                <span>{status.system.cpu_percent}%</span>
              </div>
              <div className="status-row">
                <span>Memory</span>
                <span>{status.system.memory_used_percent}%</span>
              </div>
              <div className="bar">
                <div className="bar-fill" style={{ width: `${status.system.memory_used_percent}%` }} />
              </div>
            </>
          )}
          {status.system.battery_percent !== null && status.system.battery_percent !== undefined && (
            <div className="status-row">
              <span>Battery</span>
              <span>{status.system.battery_percent}%</span>
            </div>
          )}
        </div>
      )}

      {status && status.disks.length > 0 && (
        <div className="status-block">
          <div className="status-subheading">Storage</div>
          {status.disks.map((d) => {
            const pct = Math.round((d.used_gb / d.total_gb) * 100);
            return (
              <div key={d.drive} style={{ marginBottom: 10 }}>
                <div className="status-row">
                  <span>{d.drive}</span>
                  <span>{d.free_gb} GB free</span>
                </div>
                <div className="bar">
                  <div className="bar-fill" style={{ width: `${pct}%` }} />
                </div>
              </div>
            );
          })}
        </div>
      )}

      <div className="status-block">
        <div className="status-subheading">Active Project</div>
        {activeProject?.path ? (
          <div className="muted small">{activeProject.path}</div>
        ) : (
          <div className="muted small">Nothing active — save or resume a project to see it here.</div>
        )}
      </div>

      <div className="status-block">
        <div className="status-subheading">Try asking</div>
        <div className="muted small">
          "what's on my desktop"<br />
          "find file invoice.pdf"<br />
          "what's using the most memory"<br />
          "recent downloads"
        </div>
      </div>
    </aside>
  );
}

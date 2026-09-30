import React, { useState } from "react";

export default function TabPicker({ tabs, onConfirm, disabled }) {
  const [checked, setChecked] = useState(() => new Set(tabs.map((t) => t.index)));

  const toggle = (idx) => {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const confirm = () => {
    if (checked.size === 0) {
      onConfirm("none");
      return;
    }
    onConfirm(Array.from(checked).join(","));
  };

  return (
    <div className="tab-picker">
      {tabs.map((t) => (
        <label key={t.index} className="tab-picker-row">
          <input
            type="checkbox"
            checked={checked.has(t.index)}
            onChange={() => toggle(t.index)}
            disabled={disabled}
          />
          <span className="tab-picker-title">{t.title}</span>
        </label>
      ))}
      <div className="tab-picker-actions">
        <button className="icon-btn" onClick={() => setChecked(new Set(tabs.map((t) => t.index)))} disabled={disabled}>
          Select all
        </button>
        <button className="icon-btn" onClick={() => setChecked(new Set())} disabled={disabled}>
          Select none
        </button>
        <button className="primary-btn" onClick={confirm} disabled={disabled}>
          Save selected tabs
        </button>
      </div>
    </div>
  );
}

import React, { useState } from "react";

export default function PinPrompt({ onConfirm, disabled }) {
  const [pin, setPin] = useState("");

  const submit = () => {
    if (!pin.trim()) return;
    onConfirm(pin.trim());
    setPin("");
  };

  return (
    <div className="tab-picker">
      <div className="tab-picker-row" style={{ marginBottom: 8 }}>
        <span>Enter your PIN to continue</span>
      </div>
      <input
        type="password"
        inputMode="numeric"
        value={pin}
        onChange={(e) => setPin(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && submit()}
        disabled={disabled}
        placeholder="PIN"
      />
      <div className="tab-picker-actions">
        <button className="primary-btn" onClick={submit} disabled={disabled || !pin.trim()}>
          Unlock
        </button>
      </div>
    </div>
  );
}

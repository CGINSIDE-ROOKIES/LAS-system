import React from "react";

type ButtonProps = {
  label: string;
};

export function Button({ label }: ButtonProps) {
  return (
    <button
      type="button"
      style={{
        padding: "8px 12px",
        borderRadius: 8,
        border: "1px solid #d1d5db",
        background: "#ffffff",
        cursor: "pointer"
      }}
    >
      {label}
    </button>
  );
}

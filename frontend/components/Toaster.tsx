"use client";

import { useEffect, useState } from "react";

export interface Toast {
  id: number;
  kind: "success" | "error";
  text: string;
}

let counter = 0;
type Listener = (t: Toast) => void;
const listeners = new Set<Listener>();

/** Emit a transient toast from anywhere (e.g. trade results). */
export function pushToast(kind: Toast["kind"], text: string) {
  const toast = { id: ++counter, kind, text };
  listeners.forEach((l) => l(toast));
}

/** Fixed-position stack of auto-dismissing toasts. */
export function Toaster() {
  const [toasts, setToasts] = useState<Toast[]>([]);

  useEffect(() => {
    const listener: Listener = (t) => {
      setToasts((prev) => [...prev, t]);
      setTimeout(() => {
        setToasts((prev) => prev.filter((x) => x.id !== t.id));
      }, 3500);
    };
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);

  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex flex-col gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={`animate-fade-up rounded-md border px-4 py-2 text-sm shadow-lg backdrop-blur-md ${
            t.kind === "success"
              ? "border-up/40 bg-up-dim/90 text-up"
              : "border-down/40 bg-down-dim/90 text-down"
          }`}
        >
          {t.text}
        </div>
      ))}
    </div>
  );
}

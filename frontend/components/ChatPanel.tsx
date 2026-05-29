"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { Panel } from "./Panel";
import { sendChat } from "@/lib/chatStream";
import { formatQty } from "@/lib/format";
import type { ChatActions } from "@/lib/types";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  actions?: ChatActions;
  streaming?: boolean;
}

interface ChatPanelProps {
  /** Called after the assistant finishes so the portfolio/watchlist refresh. */
  onActionsApplied: () => void;
}

let seq = 0;
const nextId = () => `m${++seq}`;

export function ChatPanel({ onActionsApplied }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages]);

  const patch = (id: string, fn: (m: ChatMessage) => ChatMessage) =>
    setMessages((prev) => prev.map((m) => (m.id === id ? fn(m) : m)));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const text = draft.trim();
    if (!text || busy) return;
    setDraft("");
    setBusy(true);

    const assistantId = nextId();
    setMessages((prev) => [
      ...prev,
      { id: nextId(), role: "user", content: text },
      { id: assistantId, role: "assistant", content: "", streaming: true },
    ]);

    let applied = false;
    await sendChat(text, {
      onToken: (chunk) =>
        patch(assistantId, (m) => ({ ...m, content: m.content + chunk })),
      onAction: (actions) => {
        applied = true;
        patch(assistantId, (m) => ({ ...m, actions }));
      },
      onDone: () => patch(assistantId, (m) => ({ ...m, streaming: false })),
      onError: (detail) =>
        patch(assistantId, (m) => ({
          ...m,
          streaming: false,
          content: m.content || `⚠ ${detail}`,
        })),
    });

    setBusy(false);
    if (applied) onActionsApplied();
  };

  return (
    <Panel title="AI Copilot" className="h-full">
      <div data-testid="chat-panel" className="flex h-full min-h-0 flex-col">
        <div ref={scrollRef} className="min-h-0 flex-1 space-y-3 overflow-auto p-3">
          {messages.length === 0 && (
            <div className="mt-6 px-2 text-center">
              <p className="font-display text-sm text-fg-muted">
                Ask FinAlly to analyze or trade.
              </p>
              <p className="mt-2 font-mono text-[11px] leading-relaxed text-fg-faint">
                &ldquo;How is my portfolio doing?&rdquo;
                <br />
                &ldquo;Buy 5 shares of NVDA&rdquo;
                <br />
                &ldquo;Add PYPL to my watchlist&rdquo;
              </p>
            </div>
          )}
          {messages.map((m) => (
            <Bubble key={m.id} message={m} />
          ))}
        </div>

        <form onSubmit={submit} className="border-t border-line p-2">
          <div className="flex items-end gap-2">
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) submit(e);
              }}
              placeholder="Message FinAlly…"
              aria-label="Message the assistant"
              data-testid="chat-input"
              rows={1}
              className="max-h-28 min-h-[40px] flex-1 resize-none rounded border border-line bg-surface-inset px-3 py-2 text-sm text-fg-primary placeholder:text-fg-faint focus:border-blue focus:outline-none"
            />
            <button
              type="submit"
              disabled={busy || !draft.trim()}
              data-testid="chat-send"
              className="rounded bg-purple px-4 py-2 font-display text-sm font-semibold text-white transition-colors hover:bg-purple-bright disabled:opacity-40"
            >
              {busy ? "…" : "Send"}
            </button>
          </div>
        </form>
      </div>
    </Panel>
  );
}

function Bubble({ message: m }: { message: ChatMessage }) {
  const isUser = m.role === "user";
  return (
    <div
      data-testid="chat-message"
      data-role={m.role}
      className={`flex ${isUser ? "justify-end" : "justify-start"} animate-fade-up`}
    >
      <div
        data-testid={isUser ? undefined : "chat-message-assistant"}
        className={`max-w-[88%] rounded-lg px-3 py-2 text-sm leading-relaxed ${
          isUser
            ? "bg-blue/15 text-fg-primary"
            : "border border-line bg-surface-raised/70 text-fg-primary"
        }`}
      >
        <p className="whitespace-pre-wrap">
          {m.content}
          {m.streaming && <span className="ml-0.5 animate-pulse-dot text-brand">▍</span>}
        </p>
        {m.actions && <ActionReceipt actions={m.actions} />}
      </div>
    </div>
  );
}

function ActionReceipt({ actions }: { actions: ChatActions }) {
  const trades = actions.trades ?? [];
  const changes = actions.watchlist_changes ?? [];
  if (trades.length === 0 && changes.length === 0) return null;
  return (
    <div
      data-testid="chat-action-confirmation"
      className="mt-2 space-y-1 border-t border-line/70 pt-2"
    >
      {trades.map((t, i) => (
        <div
          key={`t${i}`}
          className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-wide"
        >
          <span className={t.side === "buy" ? "text-up" : "text-down"}>
            {t.side}
          </span>
          <span className="text-fg-primary">
            {formatQty(t.quantity)} {t.ticker}
          </span>
        </div>
      ))}
      {changes.map((c, i) => (
        <div
          key={`w${i}`}
          className="font-mono text-[11px] uppercase tracking-wide text-blue"
        >
          {c.action} {c.ticker} · watchlist
        </div>
      ))}
    </div>
  );
}

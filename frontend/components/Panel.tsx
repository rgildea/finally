import type { ReactNode } from "react";

interface PanelProps {
  /** Short label shown in the panel's title strip. */
  title: string;
  /** Optional element rendered at the right of the title strip. */
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  /** When true the body scrolls and fills available height. */
  scroll?: boolean;
}

/**
 * The framed container every terminal panel sits in: hairline border,
 * inset surface, and a small uppercase title strip with a brand tick.
 */
export function Panel({ title, action, children, className, scroll }: PanelProps) {
  return (
    <section
      className={`flex min-h-0 flex-col overflow-hidden rounded-lg border border-line bg-surface/70 backdrop-blur-sm ${className ?? ""}`}
    >
      <header className="flex items-center justify-between gap-2 border-b border-line px-3 py-2">
        <h2 className="flex items-center gap-2 font-display text-[11px] font-semibold uppercase tracking-[0.18em] text-fg-muted">
          <span className="h-3 w-[2px] rounded-full bg-brand" />
          {title}
        </h2>
        {action}
      </header>
      <div className={`min-h-0 flex-1 ${scroll ? "overflow-auto" : ""}`}>
        {children}
      </div>
    </section>
  );
}

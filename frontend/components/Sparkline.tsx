import type { PricePoint } from "@/lib/usePriceStream";

interface SparklineProps {
  points: PricePoint[];
  width?: number;
  height?: number;
}

/**
 * Tiny inline SVG sparkline of recent prices. Colored by net direction
 * over the window. Hand-rolled (no chart lib) so the watchlist can render
 * dozens of these cheaply on every tick.
 */
export function Sparkline({ points, width = 96, height = 28 }: SparklineProps) {
  if (points.length < 2) {
    return (
      <svg width={width} height={height} aria-hidden className="opacity-40">
        <line
          x1={0}
          y1={height / 2}
          x2={width}
          y2={height / 2}
          stroke="var(--color-line-strong)"
          strokeDasharray="2 3"
        />
      </svg>
    );
  }

  const prices = points.map((p) => p.price);
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const span = max - min || 1;
  const stepX = width / (points.length - 1);
  const pad = 2;
  const usable = height - pad * 2;

  const coords = points.map((p, i) => {
    const x = i * stepX;
    const y = pad + (1 - (p.price - min) / span) * usable;
    return [x, y] as const;
  });

  const path = coords
    .map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`)
    .join(" ");

  const rising = prices[prices.length - 1] >= prices[0];
  const stroke = rising ? "var(--color-up)" : "var(--color-down)";
  const fillId = `spark-${rising ? "up" : "down"}`;
  const area = `${path} L${width} ${height} L0 ${height} Z`;

  return (
    <svg width={width} height={height} aria-hidden className="overflow-visible">
      <defs>
        <linearGradient id={fillId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={stroke} stopOpacity="0.22" />
          <stop offset="100%" stopColor={stroke} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${fillId})`} />
      <path
        d={path}
        fill="none"
        stroke={stroke}
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

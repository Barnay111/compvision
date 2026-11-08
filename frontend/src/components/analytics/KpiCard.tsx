import type { ReactNode } from 'react';

interface Props {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  live?: boolean;
}

export default function KpiCard({ label, value, hint, live }: Props) {
  return (
    <div className="rounded-2xl bg-gray-800 border border-gray-700 p-5 min-w-0">
      <p className="flex items-center gap-2 text-sm text-gray-400">
        {live && <span className="h-2 w-2 rounded-full bg-green-500" aria-hidden="true" />}
        {label}
      </p>
      <p className="mt-2 text-3xl font-semibold text-gray-100 tabular-nums truncate">{value}</p>
      {hint && <div className="mt-1 text-sm text-gray-400">{hint}</div>}
    </div>
  );
}

/** Change vs. the previous period: arrow + signed percent, so the direction never relies on color alone. */
export function Delta({ current, previous }: { current: number; previous: number }) {
  if (previous === 0) return <span className="text-gray-500">нет данных за прошлый период</span>;
  const pct = ((current - previous) / previous) * 100;
  const rounded = Math.round(pct);
  if (rounded === 0) return <span className="text-gray-400">≈ как в прошлом периоде</span>;
  const up = rounded > 0;
  return (
    <span>
      <span className={up ? 'text-green-400' : 'text-red-400'}>
        {up ? '▲' : '▼'} {up ? '+' : '−'}
        {Math.abs(rounded)}%
      </span>{' '}
      <span className="text-gray-500">к прошлому периоду</span>
    </span>
  );
}

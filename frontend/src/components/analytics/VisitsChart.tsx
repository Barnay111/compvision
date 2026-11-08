import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

// Single-series charts on the dark surface (gray-800): one hue, validated dark step.
export const SERIES_COLOR = '#3987e5';
const GRID_COLOR = '#374151'; // gray-700
const AXIS_TEXT = '#9ca3af'; // gray-400

export interface ChartPoint {
  key: string | number;
  label: string;        // axis tick
  tooltipLabel: string; // tooltip heading
  value: number;
}

interface Props {
  data: ChartPoint[];
  valueLabel: string;                   // e.g. "Визиты"
  formatValue?: (v: number) => string;
  kind?: 'bar' | 'area';
  height?: number;
  layout?: 'vertical-bars' | 'horizontal-bars';
}

const fmtDefault = (v: number) => v.toLocaleString('ru-RU', { maximumFractionDigits: 1 });

interface TooltipProps {
  active?: boolean;
  payload?: ReadonlyArray<{ payload?: unknown }>;
  valueLabel: string;
  formatValue: (v: number) => string;
}

function ChartTooltip({ active, payload, valueLabel, formatValue }: TooltipProps) {
  const point = payload?.[0]?.payload as ChartPoint | undefined;
  if (!active || !point) return null;
  return (
    <div className="rounded-lg border border-gray-600 bg-gray-900/95 px-3 py-2 text-sm shadow-xl">
      <p className="text-gray-400">{point.tooltipLabel}</p>
      <p className="mt-0.5 flex items-center gap-2 text-gray-100">
        <span className="h-2.5 w-2.5 rounded-sm" style={{ background: SERIES_COLOR }} aria-hidden="true" />
        {valueLabel}: <span className="font-semibold tabular-nums">{formatValue(point.value)}</span>
      </p>
    </div>
  );
}

export default function VisitsChart({
  data,
  valueLabel,
  formatValue = fmtDefault,
  kind = 'bar',
  height = 260,
  layout = 'vertical-bars',
}: Props) {
  const tooltip = (
    <Tooltip
      cursor={kind === 'bar' ? { fill: 'rgba(255,255,255,0.05)' } : { stroke: '#6b7280', strokeWidth: 1 }}
      content={({ active, payload }) => (
        <ChartTooltip active={active} payload={payload} valueLabel={valueLabel} formatValue={formatValue} />
      )}
      isAnimationActive={false}
    />
  );
  const axisProps = { stroke: AXIS_TEXT, tick: { fill: AXIS_TEXT, fontSize: 12 }, tickLine: false, axisLine: false };

  if (layout === 'horizontal-bars') {
    return (
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, bottom: 4, left: 8 }}>
          <CartesianGrid horizontal={false} stroke={GRID_COLOR} />
          <XAxis type="number" allowDecimals={false} {...axisProps} />
          <YAxis type="category" dataKey="label" width={96} {...axisProps} />
          {tooltip}
          <Bar dataKey="value" fill={SERIES_COLOR} maxBarSize={24} radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    );
  }

  if (kind === 'area') {
    return (
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
          <defs>
            <linearGradient id="visitsFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={SERIES_COLOR} stopOpacity={0.3} />
              <stop offset="100%" stopColor={SERIES_COLOR} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} stroke={GRID_COLOR} />
          <XAxis dataKey="label" minTickGap={24} {...axisProps} />
          <YAxis allowDecimals={false} {...axisProps} />
          {tooltip}
          <Area
            type="monotone"
            dataKey="value"
            stroke={SERIES_COLOR}
            strokeWidth={2}
            fill="url(#visitsFill)"
            activeDot={{ r: 5, stroke: '#1f2937', strokeWidth: 2 }}
          />
        </AreaChart>
      </ResponsiveContainer>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
        <CartesianGrid vertical={false} stroke={GRID_COLOR} />
        <XAxis dataKey="label" minTickGap={8} interval="preserveStartEnd" {...axisProps} />
        <YAxis allowDecimals={false} {...axisProps} />
        {tooltip}
        <Bar dataKey="value" fill={SERIES_COLOR} maxBarSize={24} radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

import { PRESETS, presetRange, type Period } from '../../lib/dates';

interface Props {
  value: Period;
  onChange: (period: Period) => void;
  maxDate: string;
}

export default function PeriodPicker({ value, onChange, maxDate }: Props) {
  const setCustom = (from: string, to: string) => {
    if (!from || !to) return;
    // Keep the range valid while the user edits either end.
    onChange(from <= to ? { preset: 'custom', from, to } : { preset: 'custom', from: to, to: from });
  };

  return (
    <div className="flex flex-wrap items-center gap-3">
      <div role="group" aria-label="Период" className="flex flex-wrap gap-1 rounded-xl bg-gray-800 p-1 border border-gray-700">
        {PRESETS.map((p) => (
          <button
            key={p.id}
            type="button"
            aria-pressed={value.preset === p.id}
            onClick={() => onChange(p.id === 'custom' ? { ...value, preset: 'custom' } : presetRange(p.id))}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              value.preset === p.id ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-gray-200'
            }`}
          >
            {p.label}
          </button>
        ))}
      </div>

      {value.preset === 'custom' && (
        <div className="flex items-center gap-2 text-sm">
          <label className="sr-only" htmlFor="period-from">С</label>
          <input
            id="period-from"
            type="date"
            value={value.from}
            max={maxDate}
            onChange={(e) => setCustom(e.target.value, value.to)}
            className="rounded-lg bg-gray-800 border border-gray-700 px-3 py-1.5 text-gray-200 [color-scheme:dark]"
          />
          <span className="text-gray-500">—</span>
          <label className="sr-only" htmlFor="period-to">По</label>
          <input
            id="period-to"
            type="date"
            value={value.to}
            max={maxDate}
            onChange={(e) => setCustom(value.from, e.target.value)}
            className="rounded-lg bg-gray-800 border border-gray-700 px-3 py-1.5 text-gray-200 [color-scheme:dark]"
          />
        </div>
      )}
    </div>
  );
}

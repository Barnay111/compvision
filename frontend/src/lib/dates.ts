/** Local-date helpers. Dates travel to the API as YYYY-MM-DD in the browser's time zone. */

export function toISODate(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function parseISODate(s: string): Date {
  const [y, m, d] = s.split('-').map(Number);
  return new Date(y, m - 1, d);
}

function addDays(d: Date, days: number): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate() + days);
}

export type PresetId = 'today' | 'yesterday' | '7d' | '30d' | 'month' | 'prev_month' | 'custom';

export interface Period {
  preset: PresetId;
  from: string;
  to: string;
}

export const PRESETS: { id: PresetId; label: string }[] = [
  { id: 'today', label: 'Сегодня' },
  { id: 'yesterday', label: 'Вчера' },
  { id: '7d', label: '7 дней' },
  { id: '30d', label: '30 дней' },
  { id: 'month', label: 'Этот месяц' },
  { id: 'prev_month', label: 'Прошлый месяц' },
  { id: 'custom', label: 'Период' },
];

export function presetRange(preset: Exclude<PresetId, 'custom'>, now = new Date()): Period {
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const range = (from: Date, to: Date): Period => ({ preset, from: toISODate(from), to: toISODate(to) });
  switch (preset) {
    case 'today':
      return range(today, today);
    case 'yesterday':
      return range(addDays(today, -1), addDays(today, -1));
    case '7d':
      return range(addDays(today, -6), today);
    case '30d':
      return range(addDays(today, -29), today);
    case 'month':
      return range(new Date(today.getFullYear(), today.getMonth(), 1), today);
    case 'prev_month':
      return range(
        new Date(today.getFullYear(), today.getMonth() - 1, 1),
        new Date(today.getFullYear(), today.getMonth(), 0),
      );
  }
}

const dayFmt = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short' });
const dayLongFmt = new Intl.DateTimeFormat('ru-RU', { weekday: 'short', day: 'numeric', month: 'long' });
const dayYearFmt = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' });

export const formatDayShort = (iso: string) => dayFmt.format(parseISODate(iso)).replace('.', '');
export const formatDayLong = (iso: string) => dayLongFmt.format(parseISODate(iso));

export function formatRange(from: string, to: string): string {
  if (from === to) return dayLongFmt.format(parseISODate(from));
  return `${dayYearFmt.format(parseISODate(from))} — ${dayYearFmt.format(parseISODate(to))}`;
}

export const WEEKDAYS_SHORT = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
export const WEEKDAYS_LONG = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье'];

export const formatHour = (h: number) => `${String(h).padStart(2, '0')}:00`;
export const formatHourRange = (h: number) => `${formatHour(h)}–${formatHour((h + 1) % 24)}`;

export function formatMinutes(min: number | null): string {
  if (min === null) return '—';
  if (min < 60) return `${Math.round(min)} мин`;
  const h = Math.floor(min / 60);
  const m = Math.round(min % 60);
  return m ? `${h} ч ${m} мин` : `${h} ч`;
}

export const formatNumber = (n: number, digits = 0) =>
  n.toLocaleString('ru-RU', { maximumFractionDigits: digits, minimumFractionDigits: 0 });

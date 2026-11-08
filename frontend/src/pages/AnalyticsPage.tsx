import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { fetchAnalytics, fetchLive, type Analytics, type LiveStats } from '../api';
import KpiCard, { Delta } from '../components/analytics/KpiCard';
import PeriodPicker from '../components/analytics/PeriodPicker';
import VisitsChart, { type ChartPoint } from '../components/analytics/VisitsChart';
import {
  formatDayLong,
  formatDayShort,
  formatHour,
  formatHourRange,
  formatMinutes,
  formatNumber,
  formatRange,
  presetRange,
  toISODate,
  WEEKDAYS_LONG,
  WEEKDAYS_SHORT,
  type Period,
} from '../lib/dates';

const PERIOD_STORAGE_KEY = 'analytics.period';
const REFRESH_MS = 60_000;
const LIVE_REFRESH_MS = 15_000;

function loadPeriod(): Period {
  try {
    const saved = JSON.parse(localStorage.getItem(PERIOD_STORAGE_KEY) ?? 'null') as Period | null;
    if (saved?.preset === 'custom' && saved.from && saved.to) return saved;
    if (saved?.preset) return presetRange(saved.preset as Exclude<Period['preset'], 'custom'>);
  } catch {
    /* storage unavailable or corrupted */
  }
  return presetRange('7d');
}

function savePeriod(period: Period) {
  try {
    localStorage.setItem(PERIOD_STORAGE_KEY, JSON.stringify(period));
  } catch {
    /* storage unavailable */
  }
}

function Card({ title, subtitle, action, children }: { title: string; subtitle?: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-2xl bg-gray-800 border border-gray-700 p-5 min-w-0">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-base font-semibold text-gray-200">{title}</h3>
          {subtitle && <p className="text-sm text-gray-400">{subtitle}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

export default function AnalyticsPage() {
  const [period, setPeriod] = useState<Period>(loadPeriod);
  const [data, setData] = useState<Analytics | null>(null);
  const [live, setLive] = useState<LiveStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [showTable, setShowTable] = useState(false);

  const [today] = useState(() => toISODate(new Date()));
  const includesToday = period.from <= today && today <= period.to;

  const changePeriod = (p: Period) => {
    setPeriod(p);
    savePeriod(p);
  };

  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      setLoading(true);
      try {
        setData(await fetchAnalytics(period.from, period.to, controller.signal));
        setError(null);
      } catch (e) {
        if (!controller.signal.aborted) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };
    load();
    // A period that includes today keeps changing — refresh it periodically.
    const interval = includesToday ? setInterval(load, REFRESH_MS) : undefined;
    return () => {
      controller.abort();
      clearInterval(interval);
    };
  }, [period.from, period.to, includesToday]);

  useEffect(() => {
    const controller = new AbortController();
    const load = () =>
      fetchLive(controller.signal)
        .then(setLive)
        .catch(() => {
          /* live card simply keeps its last value */
        });
    load();
    const interval = setInterval(load, LIVE_REFRESH_MS);
    return () => {
      controller.abort();
      clearInterval(interval);
    };
  }, []);

  const singleDay = data?.days === 1;

  const mainSeries: ChartPoint[] = useMemo(() => {
    if (!data) return [];
    if (singleDay) {
      return data.by_hour.map((h) => ({ key: h.hour, label: formatHour(h.hour), tooltipLabel: formatHourRange(h.hour), value: h.visits }));
    }
    return data.by_day.map((d) => ({ key: d.date, label: formatDayShort(d.date), tooltipLabel: formatDayLong(d.date), value: d.visits }));
  }, [data, singleDay]);

  const hourSeries: ChartPoint[] = useMemo(
    () =>
      data?.by_hour.map((h) => ({ key: h.hour, label: formatHour(h.hour), tooltipLabel: formatHourRange(h.hour), value: h.avg })) ?? [],
    [data],
  );

  const weekdaySeries: ChartPoint[] = useMemo(
    () =>
      data?.by_weekday.map((w) => ({ key: w.weekday, label: WEEKDAYS_SHORT[w.weekday], tooltipLabel: WEEKDAYS_LONG[w.weekday], value: w.avg })) ?? [],
    [data],
  );

  const dwellSeries: ChartPoint[] = useMemo(
    () => data?.dwell.map((b) => ({ key: b.label, label: b.label, tooltipLabel: `Пробыли ${b.label}`, value: b.count })) ?? [],
    [data],
  );

  const s = data?.summary;
  const dwellTotal = data?.dwell.reduce((sum, b) => sum + b.count, 0) ?? 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold text-gray-200">Посетители</h2>
          <p className="text-sm text-gray-400">
            {formatRange(period.from, period.to)}
            {loading && data && <span className="ml-2 text-gray-500">обновление…</span>}
          </p>
        </div>
        <PeriodPicker value={period} onChange={changePeriod} maxDate={today} />
      </div>

      {error && (
        <div role="alert" className="rounded-xl border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-300">
          ⚠ Не удалось загрузить аналитику: {error}
        </div>
      )}

      {!data && loading && <p className="py-20 text-center text-gray-500">Загрузка…</p>}

      {data && s && (
        <div className={`space-y-6 transition-opacity ${loading ? 'opacity-70' : ''}`}>
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6 gap-4">
            <KpiCard label="Визиты за период" value={formatNumber(s.visits)} hint={<Delta current={s.visits} previous={s.prev_visits} />} />
            <KpiCard
              label="В среднем за день"
              value={formatNumber(s.avg_per_day, 1)}
              hint={s.busiest_day ? `максимум ${s.busiest_day.visits} — ${formatDayShort(s.busiest_day.date)}` : 'нет визитов'}
            />
            <KpiCard
              live
              label="Сейчас внутри"
              value={live ? formatNumber(live.inside_now) : '—'}
              hint={live ? `сегодня ${formatNumber(live.visits_today)} визитов` : 'нет связи'}
            />
            <KpiCard
              label="Среднее время визита"
              value={formatMinutes(s.avg_dwell_min)}
              hint={s.median_dwell_min !== null ? `медиана ${formatMinutes(s.median_dwell_min)}` : 'нет завершённых визитов'}
            />
            <KpiCard label="Пиковый час" value={s.peak_hour !== null ? formatHourRange(s.peak_hour) : '—'} hint="больше всего входов" />
            <KpiCard label="Вернулись после выхода" value={formatNumber(s.returning)} hint="не считаются новыми визитами" />
          </div>

          <Card
            title={singleDay ? 'Визиты по часам' : 'Визиты по дням'}
            subtitle={singleDay ? formatDayLong(data.date_from) : undefined}
            action={
              <button
                type="button"
                onClick={() => setShowTable((v) => !v)}
                className="rounded-lg border border-gray-700 px-3 py-1 text-sm text-gray-300 hover:bg-gray-700"
              >
                {showTable ? 'График' : 'Таблица'}
              </button>
            }
          >
            {showTable ? (
              <div className="max-h-80 overflow-y-auto">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-gray-800 text-left text-gray-400">
                    <tr>
                      <th className="py-2 font-medium">{singleDay ? 'Час' : 'День'}</th>
                      <th className="py-2 text-right font-medium">Визиты</th>
                    </tr>
                  </thead>
                  <tbody>
                    {mainSeries.map((p) => (
                      <tr key={p.key} className="border-t border-gray-700/60">
                        <td className="py-1.5 text-gray-300">{p.tooltipLabel}</td>
                        <td className="py-1.5 text-right tabular-nums text-gray-100">{formatNumber(p.value)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <VisitsChart data={mainSeries} valueLabel="Визиты" kind={!singleDay && data.days > 45 ? 'area' : 'bar'} height={300} />
            )}
          </Card>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {!singleDay && (
              <Card title="Загрузка по часам" subtitle="Среднее число визитов в день по каждому часу">
                <VisitsChart data={hourSeries} valueLabel="В среднем" />
              </Card>
            )}
            {data.days >= 7 && (
              <Card title="По дням недели" subtitle="Среднее число визитов за день">
                <VisitsChart data={weekdaySeries} valueLabel="В среднем" />
              </Card>
            )}
            <Card
              title="Сколько времени проводят внутри"
              subtitle={dwellTotal ? `${formatNumber(dwellTotal)} завершённых визитов` : 'Пока нет завершённых визитов'}
            >
              <VisitsChart data={dwellSeries} valueLabel="Визиты" layout="horizontal-bars" height={240} />
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}

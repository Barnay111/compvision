export const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8002';
export const STREAM_URL = import.meta.env.VITE_STREAM_URL ?? 'http://localhost:5002/video_feed';
export const BRANCH_ID = Number(import.meta.env.VITE_BRANCH_ID ?? 1);
export const TIME_ZONE = Intl.DateTimeFormat().resolvedOptions().timeZone;

export interface EventData {
  id: number;
  branch_id: number;
  person_id: number;
  action: 'ENTER' | 'EXIT';
  timestamp: number;
  returning: boolean;
  employee_id: number | null;
}

export interface DayPoint {
  date: string;
  visits: number;
}

export interface HourPoint {
  hour: number;
  visits: number;
  avg: number;
}

export interface WeekdayPoint {
  weekday: number;
  visits: number;
  avg: number;
}

export interface DwellBucket {
  label: string;
  min_minutes: number;
  max_minutes: number | null;
  count: number;
}

export interface Analytics {
  branch_id: number;
  date_from: string;
  date_to: string;
  tz: string;
  days: number;
  summary: {
    visits: number;
    prev_visits: number;
    avg_per_day: number;
    returning: number;
    avg_dwell_min: number | null;
    median_dwell_min: number | null;
    peak_hour: number | null;
    busiest_day: DayPoint | null;
  };
  by_day: DayPoint[];
  by_hour: HourPoint[];
  by_weekday: WeekdayPoint[];
  dwell: DwellBucket[];
}

export interface LiveStats {
  branch_id: number;
  inside_now: number;
  visits_today: number;
  last_event_at: number | null;
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, { signal });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      /* body is not JSON */
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export function fetchEvents(limit = 100, signal?: AbortSignal) {
  return getJson<EventData[]>(`/events/branch/${BRANCH_ID}?limit=${limit}`, signal);
}

export function fetchAnalytics(dateFrom: string, dateTo: string, signal?: AbortSignal) {
  const params = new URLSearchParams({ date_from: dateFrom, date_to: dateTo, tz: TIME_ZONE });
  return getJson<Analytics>(`/analytics/branch/${BRANCH_ID}?${params}`, signal);
}

export function fetchLive(signal?: AbortSignal) {
  return getJson<LiveStats>(`/analytics/branch/${BRANCH_ID}/live?tz=${encodeURIComponent(TIME_ZONE)}`, signal);
}

// ---- Telegram reports ----

export interface Recipient {
  id: number;
  branch_id: number;
  name: string;
  telegram_chat_id: string;
  send_time: string;
  tz: string;
  enabled: boolean;
  last_sent_date: string | null;
}

export type RecipientInput = Pick<Recipient, 'name' | 'telegram_chat_id' | 'send_time'> & Partial<Pick<Recipient, 'tz' | 'enabled'>>;

export interface TelegramStatus {
  configured: boolean;
  bot_username: string | null;
  error: string | null;
}

export interface TelegramChat {
  chat_id: string;
  title: string;
  type: string;
}

export interface SendResult {
  ok: boolean;
  detail: string;
}

async function sendJson<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const data = await response.json();
      detail = Array.isArray(data.detail) ? data.detail.map((d: { msg: string }) => d.msg).join('; ') : data.detail ?? detail;
    } catch {
      /* body is not JSON */
    }
    throw new Error(detail);
  }
  return (response.status === 204 ? undefined : await response.json()) as T;
}

export const reportsApi = {
  status: () => getJson<TelegramStatus>('/reports/telegram/status'),
  chats: () => getJson<{ chats: TelegramChat[] }>('/reports/telegram/chats').then((r) => r.chats),
  list: () => getJson<Recipient[]>(`/reports/recipients?branch_id=${BRANCH_ID}`),
  create: (data: RecipientInput) => sendJson<Recipient>('POST', '/reports/recipients', { branch_id: BRANCH_ID, tz: TIME_ZONE, ...data }),
  update: (id: number, data: Partial<RecipientInput>) => sendJson<Recipient>('PATCH', `/reports/recipients/${id}`, data),
  remove: (id: number) => sendJson<void>('DELETE', `/reports/recipients/${id}`),
  test: (id: number) => sendJson<SendResult>('POST', `/reports/recipients/${id}/test`),
  sendNow: (id: number) => sendJson<SendResult>('POST', `/reports/recipients/${id}/send`),
  preview: () =>
    getJson<{ date: string; text: string }>(`/reports/preview/${BRANCH_ID}?tz=${encodeURIComponent(TIME_ZONE)}`),
};

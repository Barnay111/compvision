import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { reportsApi, type Recipient, type TelegramChat, type TelegramStatus } from '../api';

function Section({ title, subtitle, children }: { title: string; subtitle?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-2xl bg-gray-800 border border-gray-700 p-5 min-w-0">
      <h3 className="text-base font-semibold text-gray-200">{title}</h3>
      {subtitle && <p className="mt-0.5 text-sm text-gray-400">{subtitle}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

/** Renders the report's Telegram HTML (only <b> and <a> are used) as plain React text. */
function TelegramText({ text }: { text: string }) {
  const parts = text.replace(/<a [^>]*>(.*?)<\/a>/g, '$1').split(/(<b>.*?<\/b>)/g);
  return (
    <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-gray-200">
      {parts.map((p, i) => (p.startsWith('<b>') ? <b key={i}>{p.slice(3, -4)}</b> : p))}
    </pre>
  );
}

const inputCls = 'rounded-lg bg-gray-900 border border-gray-700 px-3 py-2 text-sm text-gray-100 placeholder-gray-500 [color-scheme:dark]';
const btnCls = 'rounded-lg border border-gray-600 px-3 py-1.5 text-sm text-gray-200 hover:bg-gray-700 disabled:opacity-50';

function RecipientRow({ r, onChange }: { r: Recipient; onChange: () => void }) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const run = async (action: () => Promise<unknown>, okText: string) => {
    setBusy(true);
    setNote(null);
    try {
      const result = (await action()) as { ok?: boolean; detail?: string } | undefined;
      if (result && result.ok === false) setNote({ ok: false, text: result.detail || 'Ошибка отправки' });
      else setNote({ ok: true, text: okText });
      onChange();
    } catch (e) {
      setNote({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <tr className="border-t border-gray-700/60 align-top">
      <td className="py-3 pr-3">
        <p className="text-gray-100">{r.name}</p>
        <p className="text-xs text-gray-500">chat {r.telegram_chat_id}</p>
        {note && (
          <p role="status" className={`mt-1 text-xs ${note.ok ? 'text-green-400' : 'text-red-400'}`}>
            {note.ok ? '✓' : '⚠'} {note.text}
          </p>
        )}
      </td>
      <td className="py-3 pr-3">
        <input
          type="time"
          aria-label={`Время отправки для ${r.name}`}
          defaultValue={r.send_time}
          onBlur={(e) => e.target.value && e.target.value !== r.send_time && run(() => reportsApi.update(r.id, { send_time: e.target.value }), 'Время сохранено')}
          className={inputCls}
        />
        <p className="mt-1 text-xs text-gray-500">{r.last_sent_date ? `последний: ${r.last_sent_date}` : 'ещё не отправлялся'}</p>
      </td>
      <td className="py-3 pr-3">
        <label className="inline-flex items-center gap-2 text-sm text-gray-300">
          <input
            type="checkbox"
            checked={r.enabled}
            disabled={busy}
            onChange={(e) => run(() => reportsApi.update(r.id, { enabled: e.target.checked }), e.target.checked ? 'Включено' : 'Выключено')}
            className="h-4 w-4 accent-blue-500"
          />
          {r.enabled ? 'вкл' : 'выкл'}
        </label>
      </td>
      <td className="py-3">
        <div className="flex flex-wrap gap-2">
          <button type="button" disabled={busy} className={btnCls} onClick={() => run(() => reportsApi.test(r.id), 'Тестовое сообщение отправлено')}>
            Тест
          </button>
          <button type="button" disabled={busy} className={btnCls} onClick={() => run(() => reportsApi.sendNow(r.id), 'Отчёт за вчера отправлен')}>
            Отправить сейчас
          </button>
          {confirmDelete ? (
            <>
              <button type="button" disabled={busy} className={`${btnCls} border-red-500/60 text-red-300`} onClick={() => run(() => reportsApi.remove(r.id), 'Удалено')}>
                Удалить навсегда
              </button>
              <button type="button" className={btnCls} onClick={() => setConfirmDelete(false)}>
                Отмена
              </button>
            </>
          ) : (
            <button type="button" disabled={busy} className={btnCls} onClick={() => setConfirmDelete(true)}>
              Удалить
            </button>
          )}
        </div>
      </td>
    </tr>
  );
}

export default function ReportsPage() {
  const [status, setStatus] = useState<TelegramStatus | null>(null);
  const [recipients, setRecipients] = useState<Recipient[]>([]);
  const [preview, setPreview] = useState<{ date: string; text: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [form, setForm] = useState({ name: '', telegram_chat_id: '', send_time: '09:00' });
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [chats, setChats] = useState<TelegramChat[] | null>(null);
  const [chatsError, setChatsError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const [s, list, p] = await Promise.all([reportsApi.status(), reportsApi.list(), reportsApi.preview()]);
      setStatus(s);
      setRecipients(list);
      setPreview(p);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial data load
    reload();
  }, [reload]);

  const findChats = async () => {
    setChatsError(null);
    try {
      setChats(await reportsApi.chats());
    } catch (e) {
      setChatsError(e instanceof Error ? e.message : String(e));
    }
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setFormError(null);
    try {
      await reportsApi.create({ ...form, name: form.name.trim(), telegram_chat_id: form.telegram_chat_id.trim() });
      setForm({ name: '', telegram_chat_id: '', send_time: form.send_time });
      setChats(null);
      await reload();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const botLink = status?.bot_username ? `https://t.me/${status.bot_username}` : null;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-gray-200">Отчёты в Telegram</h2>
        <p className="text-sm text-gray-400">Каждый день в выбранное время бот присылает итоги за вчера.</p>
      </div>

      {error && (
        <div role="alert" className="rounded-xl border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-300">
          ⚠ Не удалось загрузить данные: {error}
        </div>
      )}

      <Section title="Бот">
        {!status ? (
          <p className="text-sm text-gray-500">Проверка…</p>
        ) : status.configured ? (
          <p className="text-sm text-gray-300">
            <span className="text-green-400">✓ Подключён</span> —{' '}
            <a href={botLink!} target="_blank" rel="noreferrer" className="text-blue-300 underline">
              @{status.bot_username}
            </a>
            . Попросите получателя открыть бота и нажать <b>Start</b> (или добавить бота в групповой чат), затем найдите его чат ниже.
          </p>
        ) : (
          <div className="space-y-2 text-sm text-gray-300">
            <p className="text-yellow-300">⚠ Бот не настроен{status.error ? `: ${status.error}` : ''}</p>
            <ol className="list-decimal space-y-1 pl-5 text-gray-400">
              <li>В Telegram откройте @BotFather → <code>/newbot</code> и получите токен.</li>
              <li>
                Добавьте в <code>backend/.env</code> строку <code>TELEGRAM_BOT_TOKEN=…</code>
              </li>
              <li>Перезапустите бэкенд и обновите страницу.</li>
            </ol>
          </div>
        )}
      </Section>

      <Section title="Получатели" subtitle={`${recipients.length} получателей · время по часовому поясу браузера`}>
        {recipients.length > 0 && (
          <div className="mb-6 overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm">
              <thead className="text-left text-gray-400">
                <tr>
                  <th className="pb-2 font-medium">Кто</th>
                  <th className="pb-2 font-medium">Время</th>
                  <th className="pb-2 font-medium">Статус</th>
                  <th className="pb-2 font-medium">Действия</th>
                </tr>
              </thead>
              <tbody>
                {recipients.map((r) => (
                  <RecipientRow key={r.id} r={r} onChange={reload} />
                ))}
              </tbody>
            </table>
          </div>
        )}

        <form onSubmit={submit} className="space-y-3">
          <p className="text-sm font-medium text-gray-300">Добавить получателя</p>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_1fr_auto_auto]">
            <input
              required
              placeholder="Имя (например, Владелец)"
              aria-label="Имя"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              className={inputCls}
            />
            <input
              required
              placeholder="Chat ID"
              aria-label="Chat ID"
              value={form.telegram_chat_id}
              onChange={(e) => setForm({ ...form, telegram_chat_id: e.target.value })}
              className={inputCls}
            />
            <input
              type="time"
              required
              aria-label="Время отправки"
              value={form.send_time}
              onChange={(e) => setForm({ ...form, send_time: e.target.value })}
              className={inputCls}
            />
            <button type="submit" disabled={saving} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-50">
              {saving ? 'Сохранение…' : 'Добавить'}
            </button>
          </div>
          {formError && <p role="alert" className="text-sm text-red-400">⚠ {formError}</p>}

          <div className="text-sm">
            <button type="button" onClick={findChats} disabled={!status?.configured} className={btnCls}>
              Найти чаты, написавшие боту
            </button>
            {chatsError && <p className="mt-2 text-red-400">⚠ {chatsError}</p>}
            {chats && chats.length === 0 && (
              <p className="mt-2 text-gray-400">Никто ещё не писал боту. Попросите получателя нажать Start и повторите.</p>
            )}
            {chats && chats.length > 0 && (
              <ul className="mt-2 flex flex-wrap gap-2">
                {chats.map((c) => (
                  <li key={c.chat_id}>
                    <button
                      type="button"
                      onClick={() => setForm({ ...form, telegram_chat_id: c.chat_id, name: form.name || c.title })}
                      className="rounded-lg border border-blue-500/40 bg-blue-500/10 px-3 py-1.5 text-blue-200 hover:bg-blue-500/20"
                    >
                      {c.title} <span className="text-xs text-gray-400">({c.type === 'private' ? 'личный' : 'группа'})</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </form>
      </Section>

      <Section title="Так выглядит отчёт" subtitle={preview ? `за ${preview.date} — данные филиала` : undefined}>
        {preview ? (
          <div className="max-w-md rounded-xl bg-gray-900 border border-gray-700 p-4">
            <TelegramText text={preview.text} />
          </div>
        ) : (
          <p className="text-sm text-gray-500">Загрузка…</p>
        )}
      </Section>
    </div>
  );
}

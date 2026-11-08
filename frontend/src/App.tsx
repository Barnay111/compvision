import { useEffect, useState } from 'react';
import { BRANCH_ID } from './api';
import AnalyticsPage from './pages/AnalyticsPage';
import MonitoringPage from './pages/MonitoringPage';
import ReportsPage from './pages/ReportsPage';

type Tab = 'monitoring' | 'analytics' | 'reports';

const TABS: { id: Tab; label: string }[] = [
  { id: 'monitoring', label: 'Мониторинг' },
  { id: 'analytics', label: 'Аналитика' },
  { id: 'reports', label: 'Отчёты' },
];

function tabFromHash(): Tab {
  const hash = window.location.hash.slice(1);
  return TABS.some((t) => t.id === hash) ? (hash as Tab) : 'monitoring';
}

function App() {
  const [tab, setTab] = useState<Tab>(tabFromHash);

  useEffect(() => {
    const onHashChange = () => setTab(tabFromHash());
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  return (
    <div className="min-h-screen bg-gray-900 text-gray-100 px-4 py-6 sm:p-8 font-sans">
      <header className="mb-8 flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-wrap items-center gap-6">
          <h1 className="text-3xl font-bold bg-gradient-to-r from-blue-400 to-indigo-500 bg-clip-text text-transparent">
            CompVision AI OS
          </h1>
          <nav className="flex gap-1 rounded-xl bg-gray-800 p-1 border border-gray-700">
            {TABS.map((t) => (
              <a
                key={t.id}
                href={`#${t.id}`}
                aria-current={tab === t.id ? 'page' : undefined}
                className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                  tab === t.id ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-gray-200'
                }`}
              >
                {t.label}
              </a>
            ))}
          </nav>
        </div>
        <div className="flex items-center gap-3">
          <span className="relative flex h-3 w-3">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-3 w-3 bg-green-500"></span>
          </span>
          <span className="text-sm text-gray-400">Live Branch #{BRANCH_ID}</span>
        </div>
      </header>

      {tab === 'monitoring' && <MonitoringPage />}
      {tab === 'analytics' && <AnalyticsPage />}
      {tab === 'reports' && <ReportsPage />}
    </div>
  );
}

export default App;

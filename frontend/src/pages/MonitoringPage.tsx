import { useEffect, useState } from 'react';
import { fetchEvents, STREAM_URL, type EventData } from '../api';

export default function MonitoringPage() {
  const [events, setEvents] = useState<EventData[]>([]);

  useEffect(() => {
    // Poll the backend for the latest events every 2 seconds
    const load = async () => {
      try {
        setEvents(await fetchEvents(100));
      } catch (e) {
        console.error('Failed to fetch events', e);
      }
    };

    load();
    const interval = setInterval(load, 2000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
      {/* Camera Feed */}
      <div className="lg:col-span-2 space-y-4">
        <h2 className="text-xl font-semibold text-gray-300">Live Camera Feed</h2>
        <div className="relative rounded-2xl overflow-hidden border border-gray-700 bg-black aspect-video shadow-2xl flex items-center justify-center">
          {/* The MJPEG stream from the CV Module */}
          <img
            src={STREAM_URL}
            alt="Camera Feed"
            className="w-full h-full object-cover"
            onError={(e) => {
              (e.target as HTMLImageElement).style.display = 'none';
            }}
          />
          <div className="absolute inset-0 flex items-center justify-center -z-10 text-gray-500">
            Camera is offline. Start the CV module.
          </div>
        </div>
      </div>

      {/* Events Log */}
      <div className="space-y-4">
        <h2 className="text-xl font-semibold text-gray-300">Live Events</h2>
        <div className="bg-gray-800 rounded-2xl border border-gray-700 h-[600px] overflow-y-auto p-4 shadow-xl">
          {events.length === 0 ? (
            <p className="text-gray-500 text-center mt-10">No events detected yet.</p>
          ) : (
            <div className="space-y-3">
              {events.map((ev) => (
                <div key={ev.id} className="flex items-center justify-between p-3 rounded-lg bg-gray-700/50 border border-gray-600/50">
                  <div className="flex items-center gap-3">
                    <div className={`w-2 h-2 rounded-full ${ev.action === 'ENTER' ? 'bg-green-500' : 'bg-red-500'}`}></div>
                    <div>
                      <p className="text-sm font-medium">
                        {ev.employee_id != null ? (
                          <span className="text-sky-300">Staff #{ev.employee_id}</span>
                        ) : (
                          // person_id is unique across restarts (13 digits); the last 4 match the label on the video.
                          <>Person #{String(ev.person_id).slice(-4)}</>
                        )}
                        {ev.returning && <span className="ml-2 text-xs text-blue-300">returned</span>}
                      </p>
                      <p className="text-xs text-gray-400">{new Date(ev.timestamp * 1000).toLocaleTimeString()}</p>
                    </div>
                  </div>
                  <span className={`text-xs font-bold px-2 py-1 rounded-md ${ev.action === 'ENTER' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}`}>
                    {ev.action}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

import { useEffect, useState } from 'react';
import { useAppStore } from '../store';
import { getPendingReports, deleteReportOffline } from '../lib/idb';
import type { PendingReport } from '../lib/idb';
import { UploadCloud, Trash2, WifiOff } from 'lucide-react';

export default function Queue() {
  const { isOnline, flushQueue, updateQueueCount } = useAppStore();
  const [reports, setReports] = useState<PendingReport[]>([]);
  const [isFlushing, setIsFlushing] = useState(false);

  const loadReports = async () => {
    const data = await getPendingReports();
    setReports(data);
  };

  useEffect(() => {
    void getPendingReports().then((data) => {
      setReports(data);
    });
  }, []);

  const handleFlush = async () => {
    setIsFlushing(true);
    await flushQueue();
    await loadReports();
    setIsFlushing(false);
  };

  const handleDelete = async (id: number) => {
    if (confirm('Are you sure you want to delete this queued report?')) {
      await deleteReportOffline(id);
      await updateQueueCount();
      await loadReports();
    }
  };

  return (
    <div className="space-y-6 pb-20">
      <div className="flex justify-between items-end">
        <div>
          <h2 className="text-xl font-bold text-gray-900">Sync Queue</h2>
          <p className="text-gray-500 text-sm mt-1">Reports waiting to be sent.</p>
        </div>
        <button
          onClick={handleFlush}
          disabled={!isOnline || reports.length === 0 || isFlushing}
          className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed text-white px-4 py-2 rounded-lg font-medium flex items-center gap-2 transition-colors"
        >
          <UploadCloud className="w-4 h-4" />
          {isFlushing ? 'Sending...' : 'Sync Now'}
        </button>
      </div>

      {!isOnline && reports.length > 0 && (
        <div className="p-3 bg-orange-50 border border-orange-200 rounded-lg flex items-center gap-2 text-orange-800 text-sm">
          <WifiOff className="w-4 h-4 shrink-0" />
          You are offline. Reports will sync when connection is restored.
        </div>
      )}

      {reports.length === 0 ? (
        <div className="text-center py-10 bg-white border border-gray-200 rounded-lg">
          <p className="text-gray-500">Queue is empty.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {reports.map((report) => (
            <div key={report.id} className="p-4 bg-white border border-gray-200 rounded-lg shadow-sm flex flex-col gap-3">
              <div className="flex justify-between items-start">
                <div>
                  <h3 className="font-semibold text-gray-900">Site ID: {report.site_id}</h3>
                  <p className="text-sm text-gray-500">By {report.reporter_name} ({report.reporter_role})</p>
                </div>
                <button
                  onClick={() => handleDelete(report.id as number)}
                  className="text-red-500 hover:text-red-600 p-1"
                  title="Delete from queue"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
              <p className="text-sm bg-gray-50 p-2 rounded text-gray-700 italic border border-gray-100">
                "{report.transcript_text}"
              </p>
              {(report.photo_attachment || report.audio_attachment) && (
                <div className="text-xs text-gray-500 flex flex-wrap gap-2">
                  {report.photo_attachment && (
                    <span className="px-2 py-1 rounded-full bg-blue-50 text-blue-700">
                      Photo attached
                    </span>
                  )}
                  {report.audio_attachment && (
                    <span className="px-2 py-1 rounded-full bg-purple-50 text-purple-700">
                      Audio attached
                    </span>
                  )}
                </div>
              )}
              <div className="text-xs text-gray-400">
                Saved offline on: {new Date(report.createdAt).toLocaleString()}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

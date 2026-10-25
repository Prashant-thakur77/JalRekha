import { useState, useEffect, useMemo } from 'react';
import { useAppStore } from '../store';
import { saveReportOffline, toPendingAttachment } from '../lib/idb';
import { Send, Save, Mic, Square } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useMediaRecorder } from '../hooks/useMediaRecorder';

function formatElapsed(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, '0')}`;
}

export default function Report() {
  const { sites, isOnline, updateQueueCount, fetchSites, flushQueue } = useAppStore();
  const navigate = useNavigate();
  
  const [siteId, setSiteId] = useState('');
  const [reporterName, setReporterName] = useState('');
  const [reporterRole, setReporterRole] = useState('Community Member');
  const [transcriptText, setTranscriptText] = useState('');
  const [photoFile, setPhotoFile] = useState<File | null>(null);
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [fileInputKey, setFileInputKey] = useState(0);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const {
    isRecording,
    isSupported: isMicSupported,
    error: micError,
    audioBlob,
    elapsedMs,
    start: startRecording,
    stop: stopRecording,
    reset: resetRecording,
  } = useMediaRecorder();

  useEffect(() => {
    if (sites.length === 0 && isOnline) {
      fetchSites();
    }
  }, [sites.length, isOnline, fetchSites]);

  // When the mic produces a blob, push it into audioFile. The audioBlob
  // arrives async from MediaRecorder's onstop, so we react to it here.
  useEffect(() => {
    if (audioBlob) {
      const file = new File([audioBlob], 'note.webm', { type: 'audio/webm' });
      // eslint-disable-next-line react-hooks/set-state-in-effect -- audioBlob is an async output of the recorder hook
      setAudioFile(file);
    }
  }, [audioBlob]);

  // Build & revoke object URL for photo preview.
  const photoPreviewUrl = useMemo(
    () => (photoFile ? URL.createObjectURL(photoFile) : null),
    [photoFile],
  );
  useEffect(() => {
    return () => {
      if (photoPreviewUrl) {
        URL.revokeObjectURL(photoPreviewUrl);
      }
    };
  }, [photoPreviewUrl]);

  const handleMicToggle = async () => {
    if (isRecording) {
      stopRecording();
    } else {
      resetRecording();
      await startRecording();
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!siteId || !transcriptText || !reporterName) {
      alert('Please fill out all required fields.');
      return;
    }

    setIsSubmitting(true);
    try {
      // Offline-first approach: always save to queue first
      await saveReportOffline({
        site_id: siteId,
        reporter_name: reporterName,
        reporter_role: reporterRole,
        transcript_text: transcriptText,
        photo_attachment: toPendingAttachment(photoFile),
        audio_attachment: toPendingAttachment(audioFile),
        offline_created: !isOnline,
      });
      
      await updateQueueCount();

      if (isOnline) {
        await flushQueue();
        alert('Report submitted successfully.');
      } else {
        alert('Saved to offline queue. It will be sent when online.');
      }

      setSiteId('');
      setReporterName('');
      setTranscriptText('');
      setPhotoFile(null);
      setAudioFile(null);
      resetRecording();
      setFileInputKey((current) => current + 1);
      navigate('/dashboard');
    } catch (err) {
      console.error('Error saving report', err);
      alert('Failed to save report.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="space-y-6 pb-20">
      <div>
        <h2 className="text-xl font-bold text-gray-900">New Observation</h2>
        <p className="text-gray-500 text-sm mt-1">Submit a manual report for a monitored site.</p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Site <span className="text-red-500">*</span>
          </label>
          <select
            value={siteId}
            onChange={(e) => setSiteId(e.target.value)}
            className="w-full bg-white border border-gray-300 rounded-lg px-4 py-2.5 text-gray-900 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
            required
          >
            <option value="" disabled>Select a site</option>
            {sites.map((site) => (
              <option key={site.id} value={site.id}>
                {site.name} ({site.region})
              </option>
            ))}
          </select>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Your Name <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={reporterName}
              onChange={(e) => setReporterName(e.target.value)}
              className="w-full bg-white border border-gray-300 rounded-lg px-4 py-2.5 text-gray-900 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
              placeholder="e.g. Maria G."
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Role
            </label>
            <select
              value={reporterRole}
              onChange={(e) => setReporterRole(e.target.value)}
              className="w-full bg-white border border-gray-300 rounded-lg px-4 py-2.5 text-gray-900 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
            >
              <option value="Community Member">Community Member</option>
              <option value="Local Official">Local Official</option>
              <option value="Emergency Responder">Responder</option>
            </select>
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Observation Transcript <span className="text-red-500">*</span>
          </label>
          <div className="relative">
            <textarea
              value={transcriptText}
              onChange={(e) => setTranscriptText(e.target.value)}
              className="w-full bg-white border border-gray-300 rounded-lg px-4 py-3 min-h-[120px] text-gray-900 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none resize-none"
              placeholder="Describe the current water level, trends, and any affected areas..."
              required
            />
            <button
              type="button"
              onClick={handleMicToggle}
              disabled={!isMicSupported}
              aria-pressed={isRecording}
              className={`absolute bottom-3 right-3 p-2 rounded-full transition-colors flex items-center gap-2 ${
                isRecording
                  ? 'bg-red-100 text-red-700 hover:bg-red-200'
                  : 'bg-blue-50 text-blue-600 hover:bg-blue-100'
              } disabled:opacity-50 disabled:cursor-not-allowed`}
              title={
                !isMicSupported
                  ? 'Recording not supported'
                  : isRecording
                    ? 'Stop recording'
                    : 'Record voice note'
              }
            >
              {isRecording ? (
                <>
                  <span className="inline-block w-2 h-2 rounded-full bg-red-600 animate-pulse" aria-hidden="true" />
                  <span className="text-xs font-semibold">Recording {formatElapsed(elapsedMs)}</span>
                  <Square className="w-4 h-4" />
                </>
              ) : (
                <Mic className="w-5 h-5" />
              )}
            </button>
          </div>
          {micError && (
            <p className="mt-2 text-xs text-red-600">{micError}</p>
          )}
          {!isMicSupported && !micError && (
            <p className="mt-2 text-xs text-gray-500">Browser does not support audio recording.</p>
          )}
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Photo Evidence
            </label>
            <input
              key={`photo-${fileInputKey}`}
              type="file"
              accept="image/*"
              capture="environment"
              onChange={(e) => setPhotoFile(e.target.files?.[0] ?? null)}
              className="w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100"
            />
            {photoFile && photoPreviewUrl && (
              <div className="mt-2 flex items-center gap-2">
                <img
                  src={photoPreviewUrl}
                  alt="Preview"
                  className="w-16 h-16 object-cover rounded-lg border border-gray-200"
                />
                <p className="text-xs text-gray-500 truncate">Queued photo: {photoFile.name}</p>
              </div>
            )}
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Audio Note <span className="text-xs text-gray-400">(or upload file)</span>
            </label>
            <input
              key={`audio-${fileInputKey}`}
              type="file"
              accept="audio/*"
              onChange={(e) => setAudioFile(e.target.files?.[0] ?? null)}
              className="w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100"
            />
            {audioFile && (
              <p className="mt-2 text-xs text-gray-500">Queued audio: {audioFile.name}</p>
            )}
          </div>
        </div>

        <button
          type="submit"
          disabled={isSubmitting}
          className={`w-full py-3 px-4 rounded-lg font-bold text-white flex items-center justify-center gap-2 transition-colors ${
            isOnline 
              ? 'bg-blue-600 hover:bg-blue-700' 
              : 'bg-orange-500 hover:bg-orange-600'
          } disabled:opacity-50`}
        >
          {isSubmitting ? (
            'Saving...'
          ) : isOnline ? (
            <><Send className="w-5 h-5" /> Submit Report</>
          ) : (
            <><Save className="w-5 h-5" /> Save Offline</>
          )}
        </button>
      </form>
    </div>
  );
}

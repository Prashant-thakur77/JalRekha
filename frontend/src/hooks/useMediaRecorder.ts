import { useCallback, useEffect, useRef, useState } from 'react';

export interface UseMediaRecorderResult {
  isRecording: boolean;
  isSupported: boolean;
  error: string | null;
  audioBlob: Blob | null;
  elapsedMs: number;
  start: () => Promise<void>;
  stop: () => void;
  reset: () => void;
}

const PREFERRED_MIME = 'audio/webm;codecs=opus';
const FALLBACK_MIME = 'audio/webm';

function pickMimeType(): string | undefined {
  if (typeof MediaRecorder === 'undefined') return undefined;
  if (MediaRecorder.isTypeSupported?.(PREFERRED_MIME)) return PREFERRED_MIME;
  if (MediaRecorder.isTypeSupported?.(FALLBACK_MIME)) return FALLBACK_MIME;
  return undefined;
}

export function useMediaRecorder(): UseMediaRecorderResult {
  const isSupported =
    typeof navigator !== 'undefined' &&
    !!navigator.mediaDevices &&
    typeof MediaRecorder !== 'undefined';

  const [isRecording, setIsRecording] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null);
  const [elapsedMs, setElapsedMs] = useState(0);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startTimeRef = useRef<number>(0);
  const mimeRef = useRef<string>(FALLBACK_MIME);

  const cleanupStream = useCallback(() => {
    if (streamRef.current) {
      for (const track of streamRef.current.getTracks()) {
        track.stop();
      }
      streamRef.current = null;
    }
  }, []);

  const clearTimer = useCallback(() => {
    if (intervalRef.current !== null) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  const start = useCallback(async () => {
    setError(null);
    if (!isSupported) {
      setError('Browser does not support audio recording.');
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const mimeType = pickMimeType();
      mimeRef.current = mimeType ?? FALLBACK_MIME;
      const recorder = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream);
      recorderRef.current = recorder;
      chunksRef.current = [];

      recorder.ondataavailable = (event: BlobEvent) => {
        if (event.data && event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      };

      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: mimeRef.current });
        setAudioBlob(blob);
        cleanupStream();
        clearTimer();
        setIsRecording(false);
      };

      recorder.onerror = () => {
        setError('Recording failed.');
        cleanupStream();
        clearTimer();
        setIsRecording(false);
      };

      startTimeRef.current = Date.now();
      setElapsedMs(0);
      setAudioBlob(null);
      recorder.start();
      setIsRecording(true);

      intervalRef.current = setInterval(() => {
        setElapsedMs(Date.now() - startTimeRef.current);
      }, 100);
    } catch (err) {
      cleanupStream();
      clearTimer();
      setIsRecording(false);
      const name = (err as DOMException | null)?.name;
      if (name === 'NotAllowedError' || name === 'SecurityError') {
        setError('Microphone permission denied.');
      } else {
        setError('Recording failed.');
      }
    }
  }, [isSupported, cleanupStream, clearTimer]);

  const stop = useCallback(() => {
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== 'inactive') {
      try {
        recorder.stop();
      } catch {
        cleanupStream();
        clearTimer();
        setIsRecording(false);
        setError('Recording failed.');
      }
    } else {
      cleanupStream();
      clearTimer();
      setIsRecording(false);
    }
  }, [cleanupStream, clearTimer]);

  const reset = useCallback(() => {
    setAudioBlob(null);
    setElapsedMs(0);
    setError(null);
  }, []);

  useEffect(() => {
    return () => {
      const recorder = recorderRef.current;
      if (recorder && recorder.state !== 'inactive') {
        try {
          recorder.stop();
        } catch {
          /* ignore */
        }
      }
      cleanupStream();
      clearTimer();
    };
  }, [cleanupStream, clearTimer]);

  return { isRecording, isSupported, error, audioBlob, elapsedMs, start, stop, reset };
}

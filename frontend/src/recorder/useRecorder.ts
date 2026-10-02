import { useCallback, useEffect, useRef, useState } from "react";

/** Matches MIN_AUDIO_SECONDS / MAX_AUDIO_SECONDS in .env.example. */
export const MIN_RECORDING_MS = 500;
export const MAX_RECORDING_MS = 60_000;

/**
 * Picks a container the browser will actually record.
 *
 * Hard-coding "audio/webm" works in Chrome and throws in Firefox, where
 * MediaRecorder only offers Ogg. Asking is the portable version of that
 * assumption; an empty result means "let the browser choose".
 */
function preferredMimeType(): string {
  if (typeof MediaRecorder === "undefined") {
    return "";
  }
  for (const candidate of ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"]) {
    if (MediaRecorder.isTypeSupported(candidate)) {
      return candidate;
    }
  }
  return "";
}

export interface RecorderApi {
  recording: boolean;
  elapsedMs: number;
  supported: boolean;
  /** Rejects if the microphone is refused or unavailable. */
  start(): Promise<void>;
  /** Resolves with the clip, or null when it was too short to send. */
  stop(): Promise<Blob | null>;
  cancel(): void;
}

export function useRecorder(): RecorderApi {
  const [recording, setRecording] = useState(false);
  const [elapsedMs, setElapsedMs] = useState(0);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const startedAtRef = useRef(0);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const stopResolverRef = useRef<((blob: Blob | null) => void) | null>(null);

  const stopTicking = useCallback(() => {
    if (tickRef.current !== null) {
      clearInterval(tickRef.current);
      tickRef.current = null;
    }
  }, []);

  /** Releases the microphone. Every exit path goes through here. */
  const release = useCallback(() => {
    stopTicking();
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    recorderRef.current = null;
    setRecording(false);
    setElapsedMs(0);
  }, [stopTicking]);

  // Without this, navigating away mid-recording leaves the browser's
  // recording indicator on and the track held open.
  useEffect(() => release, [release]);

  const start = useCallback(async () => {
    if (recorderRef.current !== null) {
      return;
    }

    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    streamRef.current = stream;

    const mimeType = preferredMimeType();
    const recorder = new MediaRecorder(stream, mimeType === "" ? undefined : { mimeType });
    recorderRef.current = recorder;
    chunksRef.current = [];

    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) {
        chunksRef.current.push(event.data);
      }
    };

    recorder.onstop = () => {
      const durationMs = Date.now() - startedAtRef.current;
      const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
      release();
      const resolve = stopResolverRef.current;
      stopResolverRef.current = null;
      // Shorter than the minimum: discarded here so the user gets immediate
      // feedback, instead of uploading something the server will reject.
      resolve?.(durationMs < MIN_RECORDING_MS ? null : blob);
    };

    recorder.start();
    startedAtRef.current = Date.now();
    setRecording(true);
    tickRef.current = setInterval(() => setElapsedMs(Date.now() - startedAtRef.current), 100);
  }, [release]);

  const stop = useCallback(() => {
    const recorder = recorderRef.current;
    if (recorder === null || recorder.state === "inactive") {
      return Promise.resolve(null);
    }
    // onstop fires later, so the caller gets a promise resolved from there.
    const done = new Promise<Blob | null>((resolve) => {
      stopResolverRef.current = resolve;
    });
    recorder.stop();
    return done;
  }, []);

  const cancel = useCallback(() => {
    // Dropping the resolver first means onstop has nobody to hand a blob to.
    stopResolverRef.current = null;
    chunksRef.current = [];
    const recorder = recorderRef.current;
    if (recorder !== null && recorder.state !== "inactive") {
      recorder.stop();
    }
    release();
  }, [release]);

  return {
    recording,
    elapsedMs,
    supported: typeof MediaRecorder !== "undefined",
    start,
    stop,
    cancel,
  };
}
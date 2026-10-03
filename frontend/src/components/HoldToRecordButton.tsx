import { useCallback, useEffect, useRef, useState } from "react";

import * as api from "../api/client";
import { ApiError } from "../api/client";
import type { Message } from "../api/types";
import { MAX_RECORDING_MS, useRecorder } from "../recorder/useRecorder";

export interface HoldToRecordButtonProps {
  channelId: string;
  /** Called with the pending message so the transcript shows it right away. */
  onSent(message: Message): void;
  /** Tells the page to hold playback while the microphone is open. */
  onRecordingChange?(recording: boolean): void;
}

type SendState = "idle" | "sending" | "sent" | "error";

export default function HoldToRecordButton({ channelId, onSent, onRecordingChange }: HoldToRecordButtonProps) {
  const { recording, elapsedMs, supported, start, stop, cancel } = useRecorder();
  const [toast, setToast] = useState<string | null>(null);
  const [sendState, setSendState] = useState<SendState>("idle");

  const autoStopRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const showToast = useCallback((text: string) => {
    setToast(text);
    if (toastTimerRef.current !== null) {
      clearTimeout(toastTimerRef.current);
    }
    toastTimerRef.current = setTimeout(() => setToast(null), 3000);
  }, []);

  useEffect(
    () => () => {
      if (toastTimerRef.current !== null) {
        clearTimeout(toastTimerRef.current);
      }
    },
    [],
  );

  const finish = useCallback(async () => {
    const blob = await stop();
    if (blob === null) {
      showToast("Too short - hold a little longer.");
      return;
    }

    setSendState("sending");
    try {
      const message = await api.uploadMessage(channelId, blob);
      setSendState("sent");
      onSent(message);
      // Delivery arrives over the WebSocket in a later commit. Until then
      // "sent" is the only claim this button can honestly make.
      setTimeout(() => setSendState("idle"), 1500);
    } catch (err) {
      setSendState("error");
      showToast(err instanceof ApiError ? err.message : "Upload failed.");
    }
  }, [channelId, stop, onSent, showToast]);

  // Holding past the maximum sends on its own. Otherwise the button would
  // record indefinitely and the server would reject a clip it considers too
  // long, which reads to the user as a mysterious failure.
  useEffect(() => {
    if (!recording) {
      return;
    }
    autoStopRef.current = setTimeout(() => {
      void finish();
    }, MAX_RECORDING_MS);
    return () => {
      if (autoStopRef.current !== null) {
        clearTimeout(autoStopRef.current);
        autoStopRef.current = null;
      }
    };
  }, [recording, finish]);

  // Playback must not start while the mic is open. Reporting the recorder's
  // own state keeps that rule in one place rather than duplicating it at each
  // start/finish/cancel site.
  useEffect(() => {
    onRecordingChange?.(recording);
  }, [recording, onRecordingChange]);

  if (!supported) {
    return <p className="muted">This browser cannot record audio.</p>;
  }

  return (
    <div className="recorder">
      <button
        type="button"
        className={`recorder__button ${recording ? "recorder__button--active" : ""}`}
        onPointerDown={(event) => {
          if (recording) {
            return;
          }
          // Capture keeps every later pointer event on this element, so
          // releasing outside the button still arrives here as pointerup.
          // Without it, dragging off the button would never deliver one.
          event.currentTarget.setPointerCapture(event.pointerId);
          event.preventDefault();
          setToast(null);
          // getUserMedia rejects on refusal or a missing device; unhandled,
          // that is a console error and a button that never becomes live.
          start().catch(() => showToast("Microphone unavailable."));
        }}
        onPointerUp={() => {
          if (recording) {
            void finish();
          }
        }}
        onPointerCancel={() => {
          if (recording) {
            cancel();
            showToast("Recording cancelled.");
          }
        }}
      >
        {recording ? "Release to send" : "Hold to talk"}
      </button>

      {recording && <span className="recorder__timer">{(elapsedMs / 1000).toFixed(1)}s</span>}
      {sendState !== "idle" && sendState !== "sending" && (
        <span className={`recorder__state recorder__state--${sendState}`}>{sendState}</span>
      )}
      {toast !== null && (
        <span className="recorder__toast" role="status">
          {toast}
        </span>
      )}
    </div>
  );
}
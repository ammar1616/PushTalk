import { useState } from "react";

export interface AudioUnlockOverlayProps {
  onUnlock(): Promise<void>;
}

/**
 * Browsers refuse to start audio outside a user gesture, so the very first clip
 * cannot just play. One tap anywhere unlocks playback for the rest of the
 * session. Shown until the unlock succeeds, because a refusal leaves the queue
 * silently skipping clips.
 */
export default function AudioUnlockOverlay({ onUnlock }: AudioUnlockOverlayProps) {
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState(false);

  return (
    <div className="unlock-overlay" role="dialog" aria-label="Enable audio">
      <button
        type="button"
        className="unlock-overlay__button"
        disabled={pending}
        onClick={() => {
          setPending(true);
          setFailed(false);
          onUnlock()
            .catch(() => {
              // Still blocked: keep the overlay up so the user can try again
              // rather than leaving them with a queue that never speaks.
              setFailed(true);
            })
            .finally(() => setPending(false));
        }}
      >
        {pending ? "Enabling..." : "Tap to enable audio"}
      </button>
      {failed && <p className="unlock-overlay__hint">Audio was still blocked. Try again.</p>}
    </div>
  );
}

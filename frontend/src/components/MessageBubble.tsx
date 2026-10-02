import type { Message } from "../api/types";

/** Milliseconds -> "0:07", which is all a one-minute clip needs. */
function formatDuration(seconds: number | null): string {
  if (seconds === null) {
    return "";
  }
  const total = Math.round(seconds);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

function formatClock(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/** Marks a clip's length with a bar, so a glance shows long vs short. */
function Waveform({ peaks }: { peaks: number[] | null }) {
  if (peaks === null || peaks.length === 0) {
    return null;
  }
  return (
    <div className="wave" aria-hidden="true">
      {peaks.map((peak, index) => (
        // Peaks are a positional list, not a keyed collection, and the index is
        // the identity: reordering them would mean different audio.
        <span key={index} className="wave__bar" style={{ height: `${Math.max(peak * 100, 4)}%` }} />
      ))}
    </div>
  );
}

export default function MessageBubble({ message, isOwn }: { message: Message; isOwn: boolean }) {
  const failed = message.status === "failed";
  const playable = message.status === "ready";

  return (
    <li className={`bubble ${isOwn ? "bubble--own" : ""} ${failed ? "bubble--failed" : ""}`}>
      <div className="bubble__meta">
        <span className="bubble__sender">{isOwn ? "You" : message.sender_username}</span>
        <time className="bubble__time" dateTime={message.created_at}>
          {formatClock(message.created_at)}
        </time>
      </div>

      {failed ? (
        <p className="bubble__error">{message.failure_reason ?? "This message could not be processed."}</p>
      ) : (
        <Waveform peaks={message.waveform_peaks} />
      )}

      <div className="bubble__status">
        {playable ? (
          <>
            <span>{formatDuration(message.duration_seconds)}</span>
            {isOwn && (
              <span className="muted" title={`${message.played_count}/${message.recipient_count} played`}>
                {" "}
                {message.aggregated_status}
              </span>
            )}
          </>
        ) : (
          <span className="muted">{message.status}</span>
        )}
      </div>
    </li>
  );
}
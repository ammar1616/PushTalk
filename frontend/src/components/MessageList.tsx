import type { Message } from "../api/types";
import MessageBubble from "./MessageBubble";

export interface MessageListProps {
  messages: Message[];
  currentUserId: string;
  hasMore: boolean;
  loadingOlder: boolean;
  onLoadOlder(): void;
}

/**
 * History, oldest at the top so it reads like a transcript.
 *
 * The backend returns newest first, so the array is reversed once here rather
 * than at every call site.
 */
export default function MessageList({
  messages,
  currentUserId,
  hasMore,
  loadingOlder,
  onLoadOlder,
}: MessageListProps) {
  if (messages.length === 0) {
    return <p className="empty">No messages yet. Hold the button to send the first one.</p>;
  }

  return (
    <div className="messages">
      <div className="messages__older">
        {hasMore ? (
          <button type="button" onClick={onLoadOlder} disabled={loadingOlder}>
            {loadingOlder ? "Loading..." : "Load older"}
          </button>
        ) : (
          <span className="muted">Beginning of the channel</span>
        )}
      </div>

      <ol className="messages__list">
        {[...messages].reverse().map((message) => (
          <MessageBubble key={message.id} message={message} isOwn={message.sender_id === currentUserId} />
        ))}
      </ol>
    </div>
  );
}
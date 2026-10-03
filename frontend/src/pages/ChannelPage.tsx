import { useCallback, useEffect, useRef, useState } from "react";

import * as api from "../api/client";
import { ApiError } from "../api/client";
import type { Channel, Member, Message } from "../api/types";
import AudioUnlockOverlay from "../components/AudioUnlockOverlay";
import HoldToRecordButton from "../components/HoldToRecordButton";
import MessageList from "../components/MessageList";
import OnlineMembers from "../components/OnlineMembers";
import { usePlaybackQueue } from "../playback/usePlaybackQueue";

export interface ChannelPageProps {
  /** The full row, so the header has a name without a second request. */
  channel: Channel;
  currentUserId: string;
  onBack(): void;
}

const PAGE_SIZE = 50;

export default function ChannelPage({ channel, currentUserId, onBack }: ChannelPageProps) {
  const channelId = channel.id;
  const [members, setMembers] = useState<Member[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [hasMore, setHasMore] = useState(false);

  const { enqueue, pause, resume, clear, unlock, unlocked, playingId, pendingCount } = usePlaybackQueue(
    currentUserId,
    (item) => {
      // Best effort: a failed status write must not disturb playback.
      void api.markPlayed(item.id).catch(() => {});
    },
  );

  // Ids held when the channel opened are history, not new arrivals, so they are
  // never replayed. Anything added afterwards is enqueued.
  const historyIdsRef = useRef<Set<string> | null>(null);

  // The page holds newest-first, as the API returns it, so appending an older
  // page and reversing at render time is a concatenation rather than a merge.
  const loadInitial = useCallback(async () => {
    setLoading(true);
    try {
      const [history, roster] = await Promise.all([
        api.listMessages(channelId, null, PAGE_SIZE),
        api.listMembers(channelId),
      ]);
      setMessages(history);
      setMembers(roster);
      // A short page means the channel has fewer messages than one page can
      // hold, so there is nothing older to fetch.
      setHasMore(history.length === PAGE_SIZE);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load this channel.");
    } finally {
      setLoading(false);
    }
  }, [channelId]);

  useEffect(() => {
    void loadInitial();
  }, [loadInitial]);

  useEffect(() => {
    historyIdsRef.current = null;
    clear();
  }, [channelId, clear]);

  useEffect(() => {
    if (loading) {
      return;
    }
    if (historyIdsRef.current === null) {
      // First completed load: this is the baseline, not new audio.
      historyIdsRef.current = new Set(messages.map((message) => message.id));
      return;
    }
    const known = historyIdsRef.current;
    // Oldest-first so the queue receives them in the order they were sent.
    for (const message of [...messages].reverse()) {
      if (known.has(message.id)) {
        continue;
      }
      known.add(message.id);
      enqueue({
        id: message.id,
        sequence: message.sequence,
        url: api.mediaUrl(message.id),
        senderId: message.sender_id,
      });
    }
  }, [messages, loading, enqueue]);

  const loadOlder = useCallback(async () => {
    setLoadingOlder(true);
    try {
      // The cursor is the created_at of the oldest row already held, not the
      // current time: the backend applies a strict `created_at < before`, so
      // a "now" cursor would skip everything sent in this millisecond.
      const oldest = messages[messages.length - 1];
      if (oldest === undefined) {
        return;
      }
      const older = await api.listMessages(channelId, oldest.created_at, PAGE_SIZE);
      setMessages((current) => [...current, ...older]);
      setHasMore(older.length === PAGE_SIZE);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load older messages.");
    } finally {
      setLoadingOlder(false);
    }
  }, [channelId, messages]);

  return (
    <main className="page page--channel">
      <header className="page__header">
        <button type="button" className="link-button" onClick={onBack}>
          &larr; Channels
        </button>
        <h1>{channel.name}</h1>
      </header>

      {error !== null && (
        <p className="auth__error" role="alert">
          {error}
        </p>
      )}

      <div className="channel">
        <div className="channel__main">
          {playingId !== null && <p className="muted">Playing a message...</p>}
          {pendingCount > 0 && <p className="muted">{pendingCount} waiting to play</p>}
          {loading ? (
            <p className="muted">Loading messages...</p>
          ) : (
            <MessageList
              messages={messages}
              currentUserId={currentUserId}
              hasMore={hasMore}
              loadingOlder={loadingOlder}
              onLoadOlder={() => void loadOlder()}
            />
          )}
          <HoldToRecordButton
            channelId={channelId}
            onRecordingChange={(active) => (active ? pause() : resume())}
            onSent={(message) =>
              // The upload returns the pending row, so the transcript shows it
              // without waiting for the worker. It goes to the front because the
              // list is held newest-first, and it replaces the later copy the
              // worker event brings, matched on id.
              setMessages((current) => [message, ...current.filter((existing) => existing.id !== message.id)])
            }
          />
        </div>
        <OnlineMembers members={members} />
      </div>

      {!unlocked && <AudioUnlockOverlay onUnlock={unlock} />}
    </main>
  );
}
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { PlaybackQueue } from "./PlaybackQueue";
import type { PlaybackItem } from "./PlaybackQueue";

/**
 * A WAV with no samples. Playing it inside a real click handler is what
 * unlocks HTMLAudioElement for the session; browsers refuse audio started
 * outside a user gesture.
 */
const SILENT_WAV =
  "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA=";

export interface PlaybackApi {
  enqueue(item: PlaybackItem): void;
  pause(): void;
  resume(): void;
  clear(): void;
  /** Call from a click to unlock audio. Rejects if the browser still refuses. */
  unlock(): Promise<void>;
  unlocked: boolean;
  playingId: string | null;
  pendingCount: number;
}

export function usePlaybackQueue(
  currentUserId: string,
  onPlayed?: (item: PlaybackItem) => void,
): PlaybackApi {
  const [unlocked, setUnlocked] = useState(false);
  const [playingId, setPlayingId] = useState<string | null>(null);
  const [pendingCount, setPendingCount] = useState(0);

  // One element for all clips: playback is sequential, and reusing it keeps
  // whatever unlock the browser granted valid.
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const onPlayedRef = useRef(onPlayed);
  onPlayedRef.current = onPlayed;

  const queue = useMemo(() => {
    const play = (url: string) =>
      new Promise<void>((resolve, reject) => {
        const audio = audioRef.current ?? new Audio();
        audioRef.current = audio;
        audio.volume = 1;
        audio.src = url;
        audio.onended = () => resolve();
        audio.onerror = () => reject(new Error(`could not load audio`));
        audio.play().catch(reject);
      });

    return new PlaybackQueue({
      currentUserId,
      play,
      onStart: (item) => setPlayingId(item.id),
      onPlayed: (item) => {
        setPlayingId(null);
        onPlayedRef.current?.(item);
      },
      // A skipped clip must clear the indicator too, or the page would claim to
      // be playing something that never started.
      onFailed: () => setPlayingId(null),
      onChange: (pending) => setPendingCount(pending.length),
    });
  }, []);

  // The queue outlives a change of user, so its id is updated rather than
  // rebuilt (which would drop anything already waiting).
  useEffect(() => {
    queue.setCurrentUserId(currentUserId);
  }, [queue, currentUserId]);

  useEffect(
    () => () => {
      queue.clear();
      if (audioRef.current !== null) {
        audioRef.current.pause();
        audioRef.current.src = "";
      }
    },
    [queue],
  );

  const enqueue = useCallback((item: PlaybackItem) => queue.enqueue(item), [queue]);
  const pause = useCallback(() => queue.pause(), [queue]);
  const resume = useCallback(() => queue.resume(), [queue]);
  const clear = useCallback(() => {
    queue.clear();
    setPlayingId(null);
  }, [queue]);

  const unlock = useCallback(async () => {
    // The silent clip goes through the same element the queue will use, so the
    // gesture activates the element rather than merely the page.
    const audio = audioRef.current ?? new Audio();
    audioRef.current = audio;
    audio.volume = 0;
    audio.src = SILENT_WAV;
    await audio.play();
    setUnlocked(true);
  }, []);

  return { enqueue, pause, resume, clear, unlock, unlocked, playingId, pendingCount };
}

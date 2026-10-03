/**
 * Plays received clips one at a time, in sequence order.
 *
 * Deliberately not a React component. The ordering and pause rules are the part
 * most likely to break, and keeping them in a plain class means they can be
 * tested with a fake `play` function instead of a real browser and a real
 * audio device. `usePlaybackQueue` is the thin React wrapper.
 */

export interface PlaybackItem {
  id: string;
  sequence: number;
  url: string;
  senderId: string;
}

export interface PlaybackQueueOptions {
  /** Own messages are never played back, so the queue needs to know who that is. */
  currentUserId: string;
  /** Resolves when the clip has finished, rejects if it could not be loaded. */
  play(url: string): Promise<void>;
  /** Called when a clip actually starts, not when it is queued. */
  onStart?(item: PlaybackItem): void;
  onPlayed?(item: PlaybackItem): void;
  /** Called when a clip could not be loaded and is being skipped. */
  onFailed?(item: PlaybackItem): void;
  /** Called whenever the waiting list changes, for UI count. */
  onChange?(pending: PlaybackItem[]): void;
}

export class PlaybackQueue {
  private items: PlaybackItem[] = [];
  private readonly known = new Set<string>();
  private playing = false;
  private paused = false;
  private currentUserId: string;

  private readonly play: (url: string) => Promise<void>;
  private readonly onStart: ((item: PlaybackItem) => void) | undefined;
  private readonly onPlayed: ((item: PlaybackItem) => void) | undefined;
  private readonly onFailed: ((item: PlaybackItem) => void) | undefined;
  private readonly onChange: ((pending: PlaybackItem[]) => void) | undefined;

  constructor(options: PlaybackQueueOptions) {
    this.currentUserId = options.currentUserId;
    this.play = options.play;
    this.onStart = options.onStart;
    this.onPlayed = options.onPlayed;
    this.onFailed = options.onFailed;
    this.onChange = options.onChange;
  }

  /** Skips own messages: a sender never hears their own clip. */
  enqueue(item: PlaybackItem): void {
    if (item.senderId === this.currentUserId || this.known.has(item.id)) {
      return;
    }
    this.known.add(item.id);
    // Kept sorted by sequence rather than played in arrival order, because a
    // reconnect can deliver a catch-up batch out of order.
    const at = this.items.findIndex((queued) => queued.sequence > item.sequence);
    this.items.splice(at === -1 ? this.items.length : at, 0, item);
    this.notify();
    void this.pump();
  }

  /**
   * Holds playback while the microphone is open. An item already playing is
   * allowed to finish; only the start of the next one is held back.
   */
  pause(): void {
    this.paused = true;
  }

  resume(): void {
    if (!this.paused) {
      return;
    }
    this.paused = false;
    void this.pump();
  }

  /** A different user signed in on this device: forget their rejected ids. */
  setCurrentUserId(userId: string): void {
    this.currentUserId = userId;
  }

  clear(): void {
    this.items = [];
    this.known.clear();
    this.notify();
  }

  get isPlaying(): boolean {
    return this.playing;
  }

  get pending(): PlaybackItem[] {
    return [...this.items];
  }

  private notify(): void {
    this.onChange?.(this.pending);
  }

  private async pump(): Promise<void> {
    // One item at a time: `playing` is set before the await and cleared after,
    // and the re-entry in `finally` starts the next only once this one is done.
    if (this.playing || this.paused) {
      return;
    }
    const next = this.items.shift();
    if (next === undefined) {
      return;
    }

    this.playing = true;
    this.notify();
    this.onStart?.(next);
    try {
      await this.play(next.url);
      this.onPlayed?.(next);
    } catch {
      // A clip that will not load is skipped so it cannot block the queue
      // behind it. The caller is told so the UI does not believe it is still
      // playing something.
      this.onFailed?.(next);
    } finally {
      this.playing = false;
      void this.pump();
    }
  }
}

import { describe, expect, it } from "vitest";

import { PlaybackQueue } from "./PlaybackQueue";
import type { PlaybackItem } from "./PlaybackQueue";

const ME = "user-me";
const OTHER = "user-other";

function item(id: string, sequence: number, senderId = OTHER): PlaybackItem {
  return { id, sequence, senderId, url: `/media/${id}` };
}

/**
 * A `play` stand-in whose completion the test controls, so it can assert what
 * is running while a clip is still in flight rather than only after the fact.
 */
function controllablePlay() {
  const started: string[] = [];
  let release: (() => void) | null = null;
  let failNext = false;

  const play = (url: string): Promise<void> => {
    started.push(url);
    if (failNext) {
      failNext = false;
      return Promise.reject(new Error("load failed"));
    }
    return new Promise<void>((resolve) => {
      release = resolve;
    });
  };

  return {
    play,
    started,
    finishCurrent: () => {
      const done = release;
      release = null;
      done?.();
    },
    // The rejection rides the next call, so a test can mark one clip bad.
    failOnNextCall: () => {
      failNext = true;
    },
  };
}

/** Lets queued microtasks run so `pump()` can reach its next await. */
const flush = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

describe("PlaybackQueue", () => {
  it("keeps the backlog in sequence order even when arrivals are out of order", async () => {
    const play = controllablePlay();
    const queue = new PlaybackQueue({ currentUserId: ME, play: play.play });

    // Held so the arrivals accumulate and their order can be inspected. A clip
    // that is already playing is never preempted by a lower sequence, so this
    // is the only place ordering can be enforced.
    queue.pause();
    queue.enqueue(item("c", 3));
    queue.enqueue(item("a", 1));
    queue.enqueue(item("b", 2));

    expect(queue.pending.map((queued) => queued.id)).toEqual(["a", "b", "c"]);

    queue.resume();
    await flush();
    expect(play.started).toEqual(["/media/a"]);

    play.finishCurrent();
    await flush();
    play.finishCurrent();
    await flush();

    expect(play.started).toEqual(["/media/a", "/media/b", "/media/c"]);
  });

  it("never plays two at once", async () => {
    const play = controllablePlay();
    const queue = new PlaybackQueue({ currentUserId: ME, play: play.play });

    queue.enqueue(item("a", 1));
    queue.enqueue(item("b", 2));
    await flush();

    // Second is queued but must not have started while the first is in flight.
    expect(play.started).toEqual(["/media/a"]);
    expect(queue.isPlaying).toBe(true);

    play.finishCurrent();
    await flush();

    expect(play.started).toEqual(["/media/a", "/media/b"]);
  });

  it("skips the current user's own messages", () => {
    const play = controllablePlay();
    const queue = new PlaybackQueue({ currentUserId: ME, play: play.play });

    queue.enqueue(item("mine", 1, ME));
    queue.enqueue(item("theirs", 2, OTHER));

    expect(play.started).toEqual(["/media/theirs"]);
  });

  it("ignores a message it has already seen", () => {
    const play = controllablePlay();
    const queue = new PlaybackQueue({ currentUserId: ME, play: play.play });

    queue.enqueue(item("a", 1));
    queue.enqueue(item("a", 1));

    expect(play.started).toEqual(["/media/a"]);
    expect(queue.pending).toHaveLength(0);
  });

  it("skips a clip that fails to load and continues with the next", async () => {
    const play = controllablePlay();
    const failed: string[] = [];
    const played: string[] = [];
    const queue = new PlaybackQueue({
      currentUserId: ME,
      play: play.play,
      onFailed: (entry) => failed.push(entry.id),
      onPlayed: (entry) => played.push(entry.id),
    });

    play.failOnNextCall();
    queue.enqueue(item("bad", 1));
    queue.enqueue(item("good", 2));
    await flush();

    // The bad clip did not stall the queue: the good one is now playing.
    expect(play.started).toEqual(["/media/bad", "/media/good"]);
    expect(queue.isPlaying).toBe(true);
    // A clip that never played must not be reported as played.
    expect(failed).toEqual(["bad"]);
    expect(played).toEqual([]);
  });

  it("holds playback while paused and resumes after", async () => {
    const play = controllablePlay();
    const queue = new PlaybackQueue({ currentUserId: ME, play: play.play });

    // Paused before anything arrives, which is the recording case.
    queue.pause();
    queue.enqueue(item("a", 1));
    queue.enqueue(item("b", 2));
    await flush();

    expect(play.started).toEqual([]);
    expect(queue.pending.map((queued) => queued.id)).toEqual(["a", "b"]);

    queue.resume();
    await flush();

    expect(play.started).toEqual(["/media/a"]);
  });

  it("lets the in-flight clip finish before the pause takes effect", async () => {
    const play = controllablePlay();
    const queue = new PlaybackQueue({ currentUserId: ME, play: play.play });

    queue.enqueue(item("a", 1));
    queue.enqueue(item("b", 2));
    await flush();
    expect(play.started).toEqual(["/media/a"]);

    // Recording starts mid-clip: the current one is not cut off, but the next
    // must not begin.
    queue.pause();
    play.finishCurrent();
    await flush();

    expect(play.started).toEqual(["/media/a"]);
    expect(queue.pending.map((queued) => queued.id)).toEqual(["b"]);

    queue.resume();
    await flush();

    expect(play.started).toEqual(["/media/a", "/media/b"]);
  });

  it("reports changes and marks a played item", async () => {
    const play = controllablePlay();
    const played: string[] = [];
    const changes: number[] = [];
    const queue = new PlaybackQueue({
      currentUserId: ME,
      play: play.play,
      onPlayed: (entry) => played.push(entry.id),
      onChange: (pending) => changes.push(pending.length),
    });

    queue.enqueue(item("a", 1));
    queue.enqueue(item("b", 2));
    play.finishCurrent();
    await flush();

    expect(played).toEqual(["a"]);
    expect(changes).toContain(1);
  });

  it("forgets seen ids on clear", async () => {
    const play = controllablePlay();
    const queue = new PlaybackQueue({ currentUserId: ME, play: play.play });

    queue.enqueue(item("a", 1));
    await flush();
    play.finishCurrent();
    await flush();

    queue.clear();
    queue.enqueue(item("a", 1));
    await flush();

    expect(play.started).toEqual(["/media/a", "/media/a"]);
  });
});

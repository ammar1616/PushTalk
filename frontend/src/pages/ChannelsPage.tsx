import { useCallback, useEffect, useState, type FormEvent } from "react";

import * as api from "../api/client";
import { ApiError } from "../api/client";
import type { Channel } from "../api/types";

export interface ChannelsPageProps {
  onOpenChannel(channel: Channel): void;
}

export default function ChannelsPage({ onOpenChannel }: ChannelsPageProps) {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      setChannels(await api.listChannels());
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load channels.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function onCreate(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const created = await api.createChannel({ name });
      setName("");
      // Append rather than refetch: the creator auto-joined, so the row is
      // already one they can open, and a round trip here would be a flicker.
      setChannels((current) => [...current, created]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create the channel.");
    } finally {
      setBusy(false);
    }
  }

  async function onJoin(channelId: string) {
    setError(null);
    try {
      await api.joinChannel(channelId);
      // Refetch rather than pushing a placeholder: the header needs the name,
      // and the membership this call just created is why the channel will now
      // appear in the list at all.
      const list = await api.listChannels();
      setChannels(list);
      const joined = list.find((candidate) => candidate.id === channelId);
      if (joined === undefined) {
        setError("Joined, but that channel is not listed for this account.");
        return;
      }
      onOpenChannel(joined);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not join the channel.");
    }
  }

  return (
    <main className="page">
      <header className="page__header">
        <h1>Channels</h1>
      </header>

      <form className="channel-create" onSubmit={onCreate}>
        <label htmlFor="channel-name">New channel</label>
        <div className="channel-create__row">
          <input
            id="channel-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="team-standup"
            minLength={3}
            maxLength={64}
            required
          />
          <button type="submit" disabled={busy || name.trim().length < 3}>
            Create
          </button>
        </div>
      </form>

      {error !== null && (
        <p className="auth__error" role="alert">
          {error}
        </p>
      )}

      {loading ? (
        <p className="muted">Loading channels...</p>
      ) : (
        <ul className="channel-list">
          {channels.map((channel) => (
            <li key={channel.id} className="channel-list__item">
              <button type="button" className="channel-list__name" onClick={() => onOpenChannel(channel)}>
                {channel.name}
              </button>
            </li>
          ))}
        </ul>
      )}

      <section className="channel-join">
        <h2>Join by id</h2>
        <p className="muted">
          Channels are not listed globally, so joining one needs its id. A
          shareable invite link is the obvious next step.
        </p>
        <JoinForm onJoin={onJoin} />
      </section>
    </main>
  );
}

function JoinForm({ onJoin }: { onJoin(channelId: string): void }) {
  const [channelId, setChannelId] = useState("");

  return (
    <div className="channel-create__row">
      <input
        aria-label="Channel id"
        placeholder="channel id"
        value={channelId}
        onChange={(event) => setChannelId(event.target.value)}
      />
      <button type="button" disabled={channelId.trim().length === 0} onClick={() => onJoin(channelId.trim())}>
        Join
      </button>
    </div>
  );
}
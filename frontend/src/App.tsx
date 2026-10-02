import { useState } from "react";

import type { Channel } from "./api/types";
import { useAuth } from "./auth/useAuth";
import ChannelPage from "./pages/ChannelPage";
import ChannelsPage from "./pages/ChannelsPage";
import LoginPage from "./pages/LoginPage";

/**
 * Two screens, so navigation is one piece of state rather than a router.
 *
 * The cost is that a reload on a channel lands back on the channel list. A
 * real app fixes that with a router or a hash; neither earns its dependency
 * here, and a deep link into a channel still needs a membership check the
 * router would not provide for free.
 */
export default function App() {
  const { user, initialising, logout } = useAuth();
  const [channel, setChannel] = useState<Channel | null>(null);

  // Without this the login form renders for one frame on every reload, before
  // the stored token has been checked, and the page visibly flickers.
  if (initialising) {
    return (
      <main className="auth">
        <p>Loading...</p>
      </main>
    );
  }

  if (user === null) {
    return <LoginPage />;
  }

  return (
    <div className="app">
      <header className="shell__header">
        <h1>PushTalk</h1>
        <div className="shell__user">
          <span>{user.username}</span>
          <button type="button" onClick={logout}>
            Sign out
          </button>
        </div>
      </header>

      {channel === null ? (
        <ChannelsPage onOpenChannel={setChannel} />
      ) : (
        <ChannelPage
          key={channel.id}
          channel={channel}
          currentUserId={user.id}
          onBack={() => setChannel(null)}
        />
      )}
    </div>
  );
}
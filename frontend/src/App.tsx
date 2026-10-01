import { useAuth } from "./auth/useAuth";
import LoginPage from "./pages/LoginPage";

export default function App() {
  const { user, initialising, logout } = useAuth();

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

  // The channel list arrives in the next commit; this is the signed-in shell
  // the auth context makes possible.
  return (
    <main className="shell">
      <header className="shell__header">
        <h1>PushTalk</h1>
        <div className="shell__user">
          <span>{user.username}</span>
          <button type="button" onClick={logout}>
            Sign out
          </button>
        </div>
      </header>
    </main>
  );
}
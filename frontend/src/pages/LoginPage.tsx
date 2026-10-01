import { useState, type FormEvent } from "react";

import { ApiError } from "../api/client";
import { useAuth } from "../auth/useAuth";

type Mode = "login" | "signup";

export default function LoginPage() {
  const { login, signup } = useAuth();
  const [mode, setMode] = useState<Mode>("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const isSignup = mode === "signup";

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await (isSignup ? signup(username, password) : login(username, password));
    } catch (err) {
      // Show the backend's message rather than "something went wrong": a taken
      // username and a wrong password are the user's problem to fix, and only
      // the backend knows which one it was.
      setError(err instanceof ApiError ? err.message : "Could not reach the server.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="auth">
      <h1>PushTalk</h1>
      <p className="auth__subtitle">Push to talk voice messages.</p>

      <form className="auth__form" onSubmit={onSubmit}>
        <label htmlFor="username">Username</label>
        <input
          id="username"
          name="username"
          autoComplete="username"
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          required
        />

        <label htmlFor="password">Password</label>
        <input
          id="password"
          name="password"
          type="password"
          autoComplete={isSignup ? "new-password" : "current-password"}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          required
          minLength={isSignup ? 8 : 1}
        />

        {error !== null && (
          <p className="auth__error" role="alert">
            {error}
          </p>
        )}

        <button type="submit" disabled={submitting}>
          {submitting ? "Working..." : isSignup ? "Create account" : "Sign in"}
        </button>
      </form>

      <button
        type="button"
        className="auth__switch"
        onClick={() => {
          setMode(isSignup ? "login" : "signup");
          setError(null);
        }}
      >
        {isSignup ? "Have an account? Sign in" : "No account? Sign up"}
      </button>
    </main>
  );
}
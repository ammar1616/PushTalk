import { createContext, useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import * as api from "../api/client";
import type { User } from "../api/types";

export interface AuthContextValue {
  user: User | null;
  /** True while a stored token is being checked, to avoid flashing the login form. */
  initialising: boolean;
  login(username: string, password: string): Promise<void>;
  signup(username: string, password: string): Promise<void>;
  logout(): void;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [initialising, setInitialising] = useState(true);

  // A reload loses React state but not localStorage, so the token is still
  // there. Ask the backend who it belongs to rather than trusting the cached
  // copy: a token signed with a different JWT_SECRET would otherwise render a
  // signed-in shell that fails on the first real request.
  useEffect(() => {
    let cancelled = false;

    const restore = async () => {
      if (api.getToken() === null) {
        if (!cancelled) setInitialising(false);
        return;
      }
      try {
        const current = await api.me();
        if (!cancelled) setUser(current);
      } catch {
        // Expired, tampered with, or signed with another secret: drop it.
        api.clearToken();
        if (!cancelled) setUser(null);
      } finally {
        if (!cancelled) setInitialising(false);
      }
    };

    void restore();
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const result = await api.login({ username, password });
    api.setToken(result.access_token);
    setUser(result.user);
  }, []);

  const signup = useCallback(async (username: string, password: string) => {
    const result = await api.signup({ username, password });
    api.setToken(result.access_token);
    setUser(result.user);
  }, []);

  const logout = useCallback(() => {
    api.clearToken();
    setUser(null);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ user, initialising, login, signup, logout }),
    [user, initialising, login, signup, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
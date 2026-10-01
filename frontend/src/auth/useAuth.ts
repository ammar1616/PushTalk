import { useContext } from "react";

import { AuthContext } from "./AuthContext";

/**
 * The only supported way to read auth state.
 *
 * Throws when used outside <AuthProvider> rather than returning null, so a
 * misplaced hook fails loudly at the first render instead of as an
 * "cannot read property of undefined" somewhere further down.
 */
export function useAuth() {
  const context = useContext(AuthContext);
  if (context === null) {
    throw new Error("useAuth must be used inside <AuthProvider>");
  }
  return context;
}
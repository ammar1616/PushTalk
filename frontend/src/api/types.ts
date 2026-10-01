// Mirrors of the backend response shapes.
//
// Hand-written rather than generated: the surface is small, and a codegen step
// would need a build-time dependency on the running backend to produce three
// interfaces. The backend is the source of truth, so if these drift, the type
// error shows up at the call site in client.ts.

/** The single error shape every failing endpoint returns (SPEC.md section 7). */
export interface ApiErrorEnvelope {
  error: {
    code: string;
    message: string;
    details: Record<string, unknown>;
  };
}

export interface User {
  id: string;
  username: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface SignupRequest {
  username: string;
  password: string;
}

export type LoginRequest = Pick<SignupRequest, "username" | "password">;
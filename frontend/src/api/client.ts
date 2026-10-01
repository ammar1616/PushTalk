import type { ApiErrorEnvelope, LoginRequest, SignupRequest, TokenResponse, User } from "./types";

const TOKEN_KEY = "pushtalk.token";

/**
 * A failed request, with the backend's machine-readable code kept alongside
 * the human-readable message.
 *
 * `code` is the part worth branching on ("USERNAME_TAKEN", "AUDIO_REJECTED");
 * `message` is the part worth showing a user.
 */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export function getToken(): string | null {
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  window.localStorage.removeItem(TOKEN_KEY);
}

/**
 * Where the backend lives.
 *
 * The browser resolves this, not Docker: inside the frontend container the
 * name `backend` resolves, but the code runs in the user's browser, where only
 * the published port does. `localhost:8000` is therefore the default and
 * `VITE_API_URL` overrides it.
 *
 * Typed via a `typeof` narrowing rather than a cast, because ImportMetaEnv is
 * an index signature and would otherwise put an `any` here.
 */
function baseUrl(): string {
  const configured = import.meta.env.VITE_API_URL;
  return typeof configured === "string" && configured.length > 0
    ? configured.replace(/\/$/, "")
    : "http://localhost:8000";
}

/** Parses a failed response into an ApiError, tolerating a non-JSON body. */
async function toApiError(response: Response): Promise<ApiError> {
  let envelope: ApiErrorEnvelope | null = null;
  try {
    const body: unknown = await response.json();
    // Trust nothing about the shape: a proxy or a crash can put anything here,
    // and this code runs before any user-visible error is rendered.
    if (typeof body === "object" && body !== null && "error" in body) {
      const candidate = (body as ApiErrorEnvelope).error;
      if (typeof candidate === "object" && candidate !== null && typeof candidate.code === "string") {
        envelope = { error: { ...candidate, message: candidate.message ?? response.statusText, details: candidate.details ?? {} } };
      }
    }
  } catch {
    envelope = null;
  }

  if (!envelope) {
    return new ApiError(response.status, "NETWORK_ERROR", response.statusText || "Request failed");
  }
  return new ApiError(response.status, envelope.error.code, envelope.error.message, envelope.error.details);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");

  // <audio> and WebSocket cannot set headers, so those two paths pass ?token=
  // instead. Everything else goes in the header, where it will not end up in
  // browser history.
  const token = getToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  if (init.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${baseUrl()}${path}`, { ...init, headers });
  if (!response.ok) {
    throw await toApiError(response);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export function signup(body: SignupRequest): Promise<TokenResponse> {
  return request<TokenResponse>("/auth/signup", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function login(body: LoginRequest): Promise<TokenResponse> {
  return request<TokenResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function me(): Promise<User> {
  return request<User>("/auth/me");
}

/** URL of a message's normalized audio, with the token as a query param. */
export function mediaUrl(messageId: string): string {
  const token = getToken();
  const query = token === null ? "" : `?token=${encodeURIComponent(token)}`;
  return `${baseUrl()}/media/${messageId}${query}`;
}
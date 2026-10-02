import type {
  ApiErrorEnvelope,
  Channel,
  ChannelCreate,
  LoginRequest,
  Member,
  Message,
  SignupRequest,
  StatusAck,
  TokenResponse,
  User,
} from "./types";

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
  // Only label a body as JSON. A FormData body must be left alone: the browser
  // generates `multipart/form-data; boundary=...` itself, and a Content-Type of
  // application/json here would delete the boundary and the server would fail
  // to parse the upload.
  const isFormData = typeof FormData !== "undefined" && init.body instanceof FormData;
  if (init.body !== undefined && !isFormData && !headers.has("Content-Type")) {
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

// --- channels -----------------------------------------------------------

export function listChannels(): Promise<Channel[]> {
  return request<Channel[]>("/channels");
}

export function createChannel(body: ChannelCreate): Promise<Channel> {
  return request<Channel>("/channels", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function joinChannel(channelId: string): Promise<void> {
  // 204, so there is no body to parse. Going through request() rather than a
  // bare fetch keeps the Authorization header and error unwrapping in one
  // place instead of two.
  return request<void>(`/channels/${channelId}/join`, { method: "POST" });
}

export function listMembers(channelId: string): Promise<Member[]> {
  return request<Member[]>(`/channels/${channelId}/members`);
}

// --- messages -----------------------------------------------------------

/**
 * One page of history, newest first.
 *
 * `before` is the ISO timestamp of the oldest row already held. It is sent
 * without a sequence, so the backend applies its strict `created_at < before`
 * rule; see the note on the keyset cursor in the backend. Pass a timestamp
 * taken from the row itself, never `new Date()`, or a row written in the same
 * millisecond is skipped.
 */
export function listMessages(channelId: string, before: string | null, limit = 50): Promise<Message[]> {
  const query = new URLSearchParams();
  if (before !== null) {
    query.set("before", before);
  }
  query.set("limit", String(limit));
  return request<Message[]>(`/channels/${channelId}/messages?${query.toString()}`);
}

export function getMessage(messageId: string): Promise<Message> {
  return request<Message>(`/messages/${messageId}`);
}

export function markDelivered(messageId: string): Promise<StatusAck> {
  return request<StatusAck>(`/messages/${messageId}/delivered`, { method: "POST" });
}

export function markPlayed(messageId: string): Promise<StatusAck> {
  return request<StatusAck>(`/messages/${messageId}/played`, { method: "POST" });
}

/**
 * Upload a recorded clip.
 *
 * The blob is sent as-is and the filename is derived from the blob's own MIME
 * type. The server measures duration with ffprobe and re-encodes with ffmpeg,
 * so nothing here is trusted: the extension only has to be plausible for the
 * multipart part, and the recorded duration is never sent at all.
 */
export function uploadMessage(channelId: string, blob: Blob): Promise<Message> {
  const form = new FormData();
  const extension = blob.type.includes("ogg") ? "ogg" : blob.type.includes("mp4") ? "m4a" : "webm";
  form.append("audio", blob, `recording.${extension}`);
  return request<Message>(`/channels/${channelId}/messages`, { method: "POST", body: form });
}

/** URL of a message's normalized audio, with the token as a query param. */
export function mediaUrl(messageId: string): string {
  const token = getToken();
  const query = token === null ? "" : `?token=${encodeURIComponent(token)}`;
  return `${baseUrl()}/media/${messageId}${query}`;
}
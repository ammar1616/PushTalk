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

// --- channels -----------------------------------------------------------

export interface Channel {
  id: string;
  name: string;
  created_by: string;
  created_at: string;
}

export interface ChannelCreate {
  name: string;
}

export interface Member {
  id: string;
  username: string;
  joined_at: string;
  online: boolean;
}

// --- messages -----------------------------------------------------------

/** Lifecycle of the audio itself, not of its delivery. */
export type MessageStatus = "pending" | "processing" | "ready" | "failed";

/**
 * What the sender sees on their own message. "sent" means no recipient has
 * acknowledged it yet, which is distinct from the pending/processing/ready
 * state above.
 */
export type AggregatedStatus = "sent" | "delivered" | "played";

export interface Message {
  id: string;
  channel_id: string;
  sender_id: string;
  sender_username: string;
  status: MessageStatus;
  duration_seconds: number | null;
  waveform_peaks: number[] | null;
  failure_reason: string | null;
  created_at: string;
  sequence: number;
  delivered_count: number;
  played_count: number;
  recipient_count: number;
  aggregated_status: AggregatedStatus;
}

export interface StatusAck {
  message_id: string;
  user_id: string;
  state: string;
  aggregated_status: AggregatedStatus;
}
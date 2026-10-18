export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const TOKEN_KEY = "keshkala.token";

export type Account = {
  id: number;
  name: string;
  phone: string;
};

export type BookingSummary = {
  booking_id: string;
  conversation_id: number | null;
  status: string;
  date: string;
  time: string;
  staff_name: string;
  services: string[];
};

export type BookingLists = {
  active: BookingSummary[];
  past: BookingSummary[];
};

export type StoredMessage = {
  role: "user" | "assistant" | "choice";
  content: string;
};

export type ApiError = Error & { status: number; code?: string };

export function loadToken() {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function saveToken(token: string) {
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  window.localStorage.removeItem(TOKEN_KEY);
}

async function request<T>(path: string, options: RequestInit = {}, token?: string | null): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body) headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${API_URL}${path}`, { ...options, headers });
  const data = (await response.json().catch(() => ({}))) as {
    detail?: string | { code?: string };
  };
  if (!response.ok) {
    const detail = data.detail;
    const error = new Error(
      typeof detail === "string" ? detail : "Something went wrong. Try again.",
    ) as ApiError;
    error.status = response.status;
    if (detail && typeof detail === "object" && detail.code) error.code = detail.code;
    throw error;
  }
  return data as T;
}

export function requestOtp(phone: string, name?: string) {
  return request<{ sent: boolean }>("/api/auth/otp/request", {
    method: "POST",
    body: JSON.stringify({ phone, name: name || null }),
  });
}

export function verifyOtp(phone: string, code: string) {
  return request<{ token: string; user: Account }>("/api/auth/otp/verify", {
    method: "POST",
    body: JSON.stringify({ phone, code }),
  });
}

export function fetchMe(token: string) {
  return request<Account>("/api/auth/me", {}, token);
}

export function fetchBookings(token: string) {
  return request<BookingLists>("/api/bookings", {}, token);
}

export function fetchMessages(token: string, conversationId: number) {
  return request<{ messages: StoredMessage[] }>(
    `/api/conversations/${conversationId}/messages`,
    {},
    token,
  );
}

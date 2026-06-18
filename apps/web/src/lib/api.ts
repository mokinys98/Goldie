const DEFAULT_API_URL = "https://goldie-api-production.up.railway.app";
const DEFAULT_WS_URL = "wss://goldie-api-production.up.railway.app";

export const API_URL = (
  process.env.NODE_ENV === "development"
    ? ""
    : process.env.NEXT_PUBLIC_API_URL ?? DEFAULT_API_URL
).replace(
  /\/+$/,
  "",
);

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem("goldie_token");
}

function redirectToLogin(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem("goldie_token");
  if (window.location.pathname !== "/login") {
    window.location.assign("/login");
  }
}

export async function api<T>(
  path: string,
  options: RequestInit = {},
  authenticated = true,
): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  if (authenticated) {
    const token = getToken();
    if (!token) {
      redirectToLogin();
      throw new ApiError("Authentication required", 401);
    }
    headers.set("Authorization", `Bearer ${token}`);
  }
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers,
    cache: "no-store",
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      message = body.detail ?? body.error?.message ?? message;
    } catch {
      // Keep the status-based message.
    }
    if (authenticated && response.status === 401) {
      redirectToLogin();
    }
    throw new ApiError(message, response.status);
  }
  return response.json() as Promise<T>;
}

export function openBotStream(
  botId: string,
  onEvent: () => void,
): () => void {
  const token = getToken();
  const base = (process.env.NEXT_PUBLIC_WS_URL ?? DEFAULT_WS_URL).replace(
    /\/+$/,
    "",
  );
  if (!token) return () => undefined;
  const socket = new WebSocket(
    `${base}/api/v1/stream?token=${encodeURIComponent(token)}`,
  );
  socket.onmessage = (event) => {
    const payload = JSON.parse(event.data) as {
      bot_instance_id?: string;
      bot_instance_ids?: string[];
    };
    if (
      payload.bot_instance_id === botId
      || payload.bot_instance_ids?.includes(botId)
    ) onEvent();
  };
  return () => socket.close();
}

export type CollectorStreamEvent = {
  event_type?: string;
  market_feed_id?: string;
  collector_instance_id?: string;
  bot_instance_ids?: string[];
  status?: string;
  occurred_at?: string;
  data?: {
    observed_at?: string;
    bid?: string;
    ask?: string;
  };
};

export function openCollectorStream(
  onEvent: (event: CollectorStreamEvent) => void,
): () => void {
  const token = getToken();
  const base = (process.env.NEXT_PUBLIC_WS_URL ?? DEFAULT_WS_URL).replace(
    /\/+$/,
    "",
  );
  if (!token) return () => undefined;
  const socket = new WebSocket(
    `${base}/api/v1/stream?token=${encodeURIComponent(token)}`,
  );
  socket.onmessage = (event) => {
    const payload = JSON.parse(event.data) as CollectorStreamEvent;
    if (
      payload.event_type?.startsWith("collector.")
      || payload.event_type?.startsWith("market.")
      || payload.event_type === "instrument.specification"
    ) {
      onEvent(payload);
    }
  };
  return () => socket.close();
}

export async function downloadAuthenticated(path: string, filename: string): Promise<void> {
  const token = getToken();
  if (!token) {
    redirectToLogin();
    return;
  }
  const response = await fetch(`${API_URL}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) throw new ApiError(`Export failed (${response.status})`, response.status);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}


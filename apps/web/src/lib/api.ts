const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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

export async function api<T>(
  path: string,
  options: RequestInit = {},
  authenticated = true,
): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  if (authenticated) {
    const token = getToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
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
    throw new ApiError(message, response.status);
  }
  return response.json() as Promise<T>;
}

export function openBotStream(
  botId: string,
  onEvent: () => void,
): () => void {
  const token = getToken();
  const base = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000";
  if (!token) return () => undefined;
  const socket = new WebSocket(
    `${base}/api/v1/stream?token=${encodeURIComponent(token)}`,
  );
  socket.onmessage = (event) => {
    const payload = JSON.parse(event.data) as { bot_instance_id?: string };
    if (payload.bot_instance_id === botId) onEvent();
  };
  return () => socket.close();
}


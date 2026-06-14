"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

export type NotificationKind = "success" | "error" | "info";
export type NotificationPosition = "left" | "right";

type NotificationInput = {
  title: string;
  message?: string;
  kind?: NotificationKind;
  position?: NotificationPosition;
  duration?: number;
};

type NotificationItem = Required<NotificationInput> & {
  id: number;
};

type NotificationContextValue = {
  notify: (notification: NotificationInput) => number;
  dismiss: (id: number) => void;
};

const DEFAULT_DURATION = 10_000;
const NotificationContext = createContext<NotificationContextValue | null>(null);

export function NotificationProvider({ children }: { children: React.ReactNode }) {
  const nextId = useRef(0);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);

  const dismiss = useCallback((id: number) => {
    setNotifications((items) => items.filter((item) => item.id !== id));
  }, []);

  const notify = useCallback((input: NotificationInput) => {
    const id = ++nextId.current;
    setNotifications((items) => [
      ...items,
      {
        id,
        title: input.title,
        message: input.message ?? "",
        kind: input.kind ?? "info",
        position: input.position ?? "right",
        duration: input.duration ?? DEFAULT_DURATION,
      },
    ]);
    return id;
  }, []);

  const value = useMemo(() => ({ notify, dismiss }), [notify, dismiss]);

  return (
    <NotificationContext.Provider value={value}>
      {children}
      <NotificationViewport
        notifications={notifications}
        position="left"
        onDismiss={dismiss}
      />
      <NotificationViewport
        notifications={notifications}
        position="right"
        onDismiss={dismiss}
      />
    </NotificationContext.Provider>
  );
}

export function useNotifications(): NotificationContextValue {
  const context = useContext(NotificationContext);
  if (!context) {
    throw new Error("useNotifications must be used inside NotificationProvider");
  }
  return context;
}

function NotificationViewport({
  notifications,
  position,
  onDismiss,
}: {
  notifications: NotificationItem[];
  position: NotificationPosition;
  onDismiss: (id: number) => void;
}) {
  const visible = notifications.filter((item) => item.position === position);
  return (
    <div
      className={`notification-viewport notification-viewport-${position}`}
      aria-live="polite"
      aria-label={`${position} notifications`}
    >
      {visible.map((notification) => (
        <NotificationCard
          key={notification.id}
          notification={notification}
          onDismiss={onDismiss}
        />
      ))}
    </div>
  );
}

function NotificationCard({
  notification,
  onDismiss,
}: {
  notification: NotificationItem;
  onDismiss: (id: number) => void;
}) {
  useEffect(() => {
    const timer = window.setTimeout(
      () => onDismiss(notification.id),
      notification.duration,
    );
    return () => window.clearTimeout(timer);
  }, [notification.duration, notification.id, onDismiss]);

  return (
    <div
      className={`notification notification-${notification.kind}`}
      role={notification.kind === "error" ? "alert" : "status"}
    >
      <div className="notification-content">
        <strong>{notification.title}</strong>
        {notification.message && <p>{notification.message}</p>}
      </div>
      <button
        aria-label="Close notification"
        className="notification-close"
        onClick={() => onDismiss(notification.id)}
        type="button"
      >
        x
      </button>
      <div
        className="notification-timer"
        style={{ animationDuration: `${notification.duration}ms` }}
      />
    </div>
  );
}

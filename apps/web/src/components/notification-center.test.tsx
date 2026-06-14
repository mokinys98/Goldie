import React from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  NotificationProvider,
  useNotifications,
} from "./notification-center";

function Trigger() {
  const { notify } = useNotifications();
  return (
    <button
      onClick={() =>
        notify({
          kind: "success",
          position: "right",
          title: "Saved",
          message: "The change was applied.",
        })
      }
    >
      Notify
    </button>
  );
}

describe("NotificationProvider", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("renders and manually dismisses a notification", () => {
    render(
      <NotificationProvider>
        <Trigger />
      </NotificationProvider>,
    );

    fireEvent.click(screen.getByText("Notify"));
    expect(screen.getByText("Saved")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Close notification"));
    expect(screen.queryByText("Saved")).not.toBeInTheDocument();
  });

  it("automatically closes after ten seconds", () => {
    vi.useFakeTimers();
    render(
      <NotificationProvider>
        <Trigger />
      </NotificationProvider>,
    );

    fireEvent.click(screen.getByText("Notify"));
    act(() => vi.advanceTimersByTime(10_000));
    expect(screen.queryByText("Saved")).not.toBeInTheDocument();
  });
});

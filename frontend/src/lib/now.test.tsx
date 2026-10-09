import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useNow } from "./now";

function Clock() {
  return <span>{useNow().toISOString()}</span>;
}

describe("useNow", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-08T12:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("starts at the current time", () => {
    render(<Clock />);

    expect(screen.getByText("2026-10-08T12:00:00.000Z")).toBeInTheDocument();
  });

  it("moves on every 30 seconds, so relative times do not go stale", () => {
    render(<Clock />);

    act(() => {
      vi.advanceTimersByTime(30_000);
    });

    expect(screen.getByText("2026-10-08T12:00:30.000Z")).toBeInTheDocument();
  });

  it("stops ticking after unmount", () => {
    const { unmount } = render(<Clock />);
    unmount();

    expect(vi.getTimerCount()).toBe(0);
  });
});

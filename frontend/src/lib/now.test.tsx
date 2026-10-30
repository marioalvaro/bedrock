import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { localIsoDate, useNow } from "./now";

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

describe("localIsoDate", () => {
  it("is the local calendar date, zero padded, even late in the evening", () => {
    expect(localIsoDate(new Date(2026, 0, 5, 23, 59))).toBe("2026-01-05");
    expect(localIsoDate(new Date(2026, 9, 23, 0, 1))).toBe("2026-10-23");
  });
});

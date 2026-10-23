import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { usePrefersReducedMotion } from "./motion";

const original = window.matchMedia;

// A matchMedia whose `(prefers-reduced-motion: reduce)` answer can change later.
function stubReducedMotion(initial: boolean) {
  let matches = initial;
  const listeners = new Set<() => void>();
  window.matchMedia = vi.fn((query: string) => ({
    get matches() {
      return query === "(prefers-reduced-motion: reduce)" && matches;
    },
    media: query,
    addEventListener: (_: string, listener: () => void) => listeners.add(listener),
    removeEventListener: (_: string, listener: () => void) => listeners.delete(listener),
  })) as unknown as typeof window.matchMedia;
  return (value: boolean) => {
    matches = value;
    listeners.forEach((listener) => listener());
  };
}

function Probe() {
  return <span>{usePrefersReducedMotion() ? "reduced" : "full"}</span>;
}

describe("usePrefersReducedMotion", () => {
  afterEach(() => {
    window.matchMedia = original;
  });

  it("is false when the OS has no motion preference", () => {
    stubReducedMotion(false);
    render(<Probe />);

    expect(screen.getByText("full")).toBeInTheDocument();
  });

  it("is true when the OS asks to reduce motion", () => {
    stubReducedMotion(true);
    render(<Probe />);

    expect(screen.getByText("reduced")).toBeInTheDocument();
  });

  it("follows a change of the preference while the page is open", () => {
    const set = stubReducedMotion(false);
    render(<Probe />);

    act(() => set(true));

    expect(screen.getByText("reduced")).toBeInTheDocument();
  });
});

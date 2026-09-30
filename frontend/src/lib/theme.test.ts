import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { applyTheme, getInitialTheme } from "./theme";

describe("getInitialTheme", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.classList.remove("dark");
  });

  it("prefers the stored value over the media query", () => {
    localStorage.setItem("theme", "dark");
    vi.spyOn(window, "matchMedia").mockReturnValue({
      matches: false,
    } as MediaQueryList);

    expect(getInitialTheme()).toBe("dark");
  });

  it("falls back to the media query when nothing is stored", () => {
    vi.spyOn(window, "matchMedia").mockReturnValue({
      matches: true,
    } as MediaQueryList);

    expect(getInitialTheme()).toBe("dark");
  });

  it("falls back to light when the media query does not match and nothing is stored", () => {
    vi.spyOn(window, "matchMedia").mockReturnValue({
      matches: false,
    } as MediaQueryList);

    expect(getInitialTheme()).toBe("light");
  });
});

describe("applyTheme", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.classList.remove("dark");
  });

  afterEach(() => {
    document.documentElement.classList.remove("dark");
  });

  it("adds the dark class and persists dark", () => {
    applyTheme("dark");

    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(localStorage.getItem("theme")).toBe("dark");
  });

  it("removes the dark class and persists light", () => {
    document.documentElement.classList.add("dark");

    applyTheme("light");

    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(localStorage.getItem("theme")).toBe("light");
  });
});

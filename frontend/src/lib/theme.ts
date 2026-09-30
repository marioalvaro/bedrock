import { useSyncExternalStore } from "react";

export type Theme = "light" | "dark";

const STORAGE_KEY = "theme";

export function getInitialTheme(): Theme {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === "light" || stored === "dark") {
    return stored;
  }

  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyTheme(theme: Theme): void {
  document.documentElement.classList.toggle("dark", theme === "dark");
  localStorage.setItem(STORAGE_KEY, theme);
}

// One theme for the whole page, so every toggle rendered at once stays in sync.
let currentTheme: Theme | undefined;
const listeners = new Set<() => void>();

function getTheme(): Theme {
  currentTheme ??= getInitialTheme();
  return currentTheme;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function setTheme(theme: Theme): void {
  currentTheme = theme;
  applyTheme(theme);
  listeners.forEach((listener) => listener());
}

export function useTheme(): Theme {
  return useSyncExternalStore(subscribe, getTheme);
}

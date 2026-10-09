import { useSyncExternalStore } from "react";

export type Scale = "K" | "M" | "B";

export const SCALES: readonly Scale[] = ["K", "M", "B"];

const STORAGE_KEY = "scale";
const DEFAULT_SCALE: Scale = "M";

function isScale(value: string | null): value is Scale {
  return value === "K" || value === "M" || value === "B";
}

function readStored(): Scale {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return isScale(stored) ? stored : DEFAULT_SCALE;
  } catch {
    return DEFAULT_SCALE;
  }
}

// One scale for the whole page, so every toggle rendered at once stays in sync (Gotcha G5).
let currentScale: Scale | undefined;
const listeners = new Set<() => void>();

export function getScale(): Scale {
  currentScale ??= readStored();
  return currentScale;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function setScale(scale: Scale): void {
  currentScale = scale;
  try {
    localStorage.setItem(STORAGE_KEY, scale);
  } catch {
    // Persistence is a convenience; the in-memory value still applies.
  }
  listeners.forEach((listener) => listener());
}

export function useScale(): Scale {
  return useSyncExternalStore(subscribe, getScale);
}

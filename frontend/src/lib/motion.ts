import { useSyncExternalStore } from "react";

const REDUCE = "(prefers-reduced-motion: reduce)";

function subscribe(listener: () => void): () => void {
  const query = window.matchMedia(REDUCE);
  query.addEventListener("change", listener);
  return () => query.removeEventListener("change", listener);
}

const getSnapshot = () => window.matchMedia(REDUCE).matches;

// Whether the OS asks for less motion; JS-driven animation (AG Grid rows) checks this, CSS
// transitions use the `--motion-fast` token, which `index.css` zeroes under the same query.
export function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot);
}

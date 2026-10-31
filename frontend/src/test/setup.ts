import "@testing-library/jest-dom/vitest";
import { AllCommunityModule, ModuleRegistry } from "ag-grid-community";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// main.tsx registers these for the app; without them AG Grid ignores cellClass and more.
ModuleRegistry.registerModules([AllCommunityModule]);

if (!window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList;
}

// jsdom has no 2D canvas and logs "Not implemented" on every call; a browser without one returns
// null, which is what the chart wrapper's color reading expects.
HTMLCanvasElement.prototype.getContext = (() =>
  null) as typeof HTMLCanvasElement.prototype.getContext;

// Vitest runs without globals, so Testing Library cannot register this itself.
afterEach(() => {
  cleanup();
});

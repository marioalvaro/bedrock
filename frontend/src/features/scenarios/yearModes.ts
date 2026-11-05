import { createContext } from "react";

import type { YearModeOut } from "@/api/generated/types.gen";

export type YearModeValue = YearModeOut["mode"];

// What the year headers need from the grid: the scenario's modes and the switch itself. AG Grid
// renders header components outside the column definitions' closures, so they read it from here.
export interface YearModes {
  modes: Map<number, YearModeOut>;
  disabled: boolean;
  onMode: (year: number, mode: YearModeValue) => void;
}

export const YearModesContext = createContext<YearModes>({
  modes: new Map(),
  disabled: true,
  onMode: () => {},
});

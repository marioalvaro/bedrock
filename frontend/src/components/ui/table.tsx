import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

// The app's compact data tables: one padding and no wrapping for every cell, numbers right-aligned
// in tabular figures (`num`). A caller's `className` wins over these defaults.
const CELL = "px-2 py-1 whitespace-nowrap";

type CellProps<T extends "th" | "td"> = ComponentProps<T> & { numeric?: boolean };

/** A column or row header: muted, normal weight, left-aligned (right with `numeric`). */
export function Th({ numeric = false, className, ...props }: CellProps<"th">) {
  return (
    <th
      className={cn(
        "text-muted-foreground font-normal",
        CELL,
        numeric ? "text-right" : "text-left",
        className,
      )}
      {...props}
    />
  );
}

/** A data cell; `numeric` right-aligns it in tabular figures. */
export function Td({ numeric = false, className, ...props }: CellProps<"td">) {
  return <td className={cn(CELL, numeric && "num text-right", className)} {...props} />;
}

import { useEffect, useState } from "react";

const TICK_MS = 30_000;

// The current time, refreshed every 30 s so "2h ago" labels do not go stale.
export function useNow(): Date {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), TICK_MS);
    return () => clearInterval(id);
  }, []);

  return now;
}

// The local calendar date as YYYY-MM-DD (what a date input holds), not the UTC date.
export function localIsoDate(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

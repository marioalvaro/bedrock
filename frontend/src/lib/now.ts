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

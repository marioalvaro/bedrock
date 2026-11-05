import { useEffect } from "react";
import { useLocation } from "react-router";

/** Reports the router's query string each time it changes (tests read where a view left the URL). */
export function LocationProbe({ onSearch }: { onSearch: (search: string) => void }) {
  const { search } = useLocation();
  useEffect(() => {
    onSearch(search);
  }, [search, onSearch]);
  return null;
}

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import {
  companyErrorMessage,
  companyKey,
  companyQueryOptions,
  useBackfillFilings,
} from "@/api/companies";
import { ApiError } from "@/api/errors";
import type { CompanyListItem } from "@/api/generated/types.gen";
import { Button } from "@/components/ui/button";

// About 1-2 minutes per company at SEC's rate (docs/erd/data-coverage.md, "Flow"): a poll every
// few seconds shows the count rise without loading the server.
const POLL_MS = 5_000;
// The count must stay put for this many polls in a row (two intervals, 10 s) before the run counts
// as finished: one filing can take several seconds to fetch, and failed or absent filings never
// count as read.
const STABLE_POLLS = 3;

/** "Filings read: X of Y" and a "Read all filings" button (FR-DATA-21, M7b S8). While a backfill
 * runs the company is polled until `filings_parsed` stops changing or reaches `filings_total`;
 * then the company's views are refreshed, since new face lines can fill cells. */
export function FilingsStatus({
  company,
  pollMs = POLL_MS,
}: {
  company: CompanyListItem;
  pollMs?: number;
}) {
  const queryClient = useQueryClient();
  const backfill = useBackfillFilings(company.ticker);
  const [following, setFollowing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { data, dataUpdatedAt } = useQuery({
    ...companyQueryOptions(company.ticker),
    enabled: following,
    refetchInterval: following ? pollMs : false,
    initialData: company,
    initialDataUpdatedAt: 0,
  });
  const seen = useRef<{ parsed: number; same: number } | null>(null);
  const startedAt = useRef(0); // only a poll answered after the start counts

  useEffect(() => {
    if (!following || dataUpdatedAt <= startedAt.current || !data) return;
    const last = seen.current;
    const same = last !== null && last.parsed === data.filings_parsed ? last.same + 1 : 0;
    seen.current = { parsed: data.filings_parsed, same };
    if (same >= STABLE_POLLS - 1 || data.filings_parsed >= data.filings_total) {
      setFollowing(false);
      void queryClient.invalidateQueries({ queryKey: companyKey(company.ticker) });
    }
  }, [following, data, dataUpdatedAt, queryClient, company.ticker]);

  if (company.source !== "sec") return null;
  const shown = data ?? company; // the shared company query: the header's too

  function start() {
    setError(null);
    backfill.mutate(undefined, {
      onSuccess: () => follow(),
      onError: (e) => {
        if (e instanceof ApiError && e.status === 409) follow();
        else setError(companyErrorMessage(e, "Could not start reading the filings."));
      },
    });
  }

  function follow() {
    seen.current = null;
    startedAt.current = Date.now();
    setFollowing(true);
  }

  const running = following || backfill.isPending;
  return (
    <span className="flex items-center gap-2">
      <span className="text-muted-foreground text-xs tabular-nums">
        Filings read: {shown.filings_parsed} of {shown.filings_total}
      </span>
      <Button
        variant="outline"
        size="xs"
        disabled={running || shown.filings_total === 0}
        onClick={start}
      >
        {running ? "Reading filings…" : "Read all filings"}
      </Button>
      {error && (
        <span role="alert" className="text-destructive text-xs">
          {error}
        </span>
      )}
    </span>
  );
}

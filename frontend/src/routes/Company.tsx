import { useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { NavLink, useParams } from "react-router";

import { companyErrorMessage, companyQueryOptions, useRefreshCompany } from "@/api/companies";
import { ApiError } from "@/api/errors";
import type { StatementType } from "@/api/statements";
import { Button } from "@/components/ui/button";
import { Overview } from "@/features/overview/Overview";
import { StatementView } from "@/features/statements/StatementView";
import { formatCompact, formatPrice, formatRelative } from "@/lib/format";
import { useNow } from "@/lib/now";

const TABS: { slug: string; label: string; statement?: StatementType }[] = [
  { slug: "overview", label: "Overview" },
  { slug: "income", label: "Income", statement: "IS" },
  { slug: "balance", label: "Balance", statement: "BS" },
  { slug: "cash-flow", label: "Cash Flow", statement: "CF" },
];

const tabPath = (ticker: string, slug: string) =>
  slug === "overview" ? `/c/${ticker}` : `/c/${ticker}/${slug}`;

const tabClassName = ({ isActive }: { isActive: boolean }) =>
  isActive
    ? "border-foreground text-foreground -mb-px border-b py-2 whitespace-nowrap"
    : "text-muted-foreground hover:text-foreground py-2 whitespace-nowrap";

export function Company() {
  const { ticker = "", tab = "overview" } = useParams<{ ticker: string; tab?: string }>();
  const { data: company, isPending, error } = useQuery(companyQueryOptions(ticker));
  const refresh = useRefreshCompany(ticker);
  const now = useNow();

  if (isPending) return null;
  if (!company) {
    const notFound = error instanceof ApiError && error.status === 404;
    return (
      <p className="text-destructive p-4 text-sm">
        {notFound ? "Company not found." : "Could not load the company."}
      </p>
    );
  }

  const active = TABS.find((candidate) => candidate.slug === tab) ?? TABS[0]!;

  return (
    <div>
      <div className="border-border flex flex-wrap items-baseline gap-x-4 gap-y-1 border-b px-4 py-2">
        <h1 className="text-base font-medium">{company.ticker}</h1>
        <span className="text-muted-foreground">{company.name}</span>
        <span data-testid="header-price" className="num">
          {formatPrice(company.price)}
        </span>
        <span data-testid="header-market-cap" className="num text-muted-foreground">
          {formatCompact(company.market_cap)}
        </span>
        <span className="ml-auto flex items-center gap-2">
          <span className="text-muted-foreground text-xs">
            Refreshed {formatRelative(company.last_refreshed_at, now)}
          </span>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Refresh"
            disabled={refresh.isPending}
            onClick={() => refresh.mutate()}
          >
            <RefreshCw className={refresh.isPending ? "animate-spin" : undefined} />
          </Button>
        </span>
        {refresh.isError && (
          <p role="alert" className="text-destructive basis-full text-sm">
            {companyErrorMessage(refresh.error, "Could not refresh the company.")}
          </p>
        )}
        {refresh.data?.warnings.map((warning) => (
          <p key={warning} className="text-muted-foreground basis-full text-sm">
            {warning}
          </p>
        ))}
      </div>
      <nav className="border-border flex gap-4 overflow-x-auto border-b px-4 text-sm">
        {TABS.map(({ slug, label }) => (
          <NavLink key={slug} to={tabPath(company.ticker, slug)} end className={tabClassName}>
            {label}
          </NavLink>
        ))}
      </nav>
      {active.statement ? (
        <StatementView
          key={active.slug}
          ticker={company.ticker}
          cik={company.cik}
          type={active.statement}
        />
      ) : (
        <Overview company={company} />
      )}
    </div>
  );
}

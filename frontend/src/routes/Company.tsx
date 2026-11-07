import { useQuery } from "@tanstack/react-query";
import { Fragment, type ReactNode } from "react";
import { RefreshCw } from "lucide-react";
import { NavLink, useParams, useSearchParams } from "react-router";

import { companyErrorMessage, companyQueryOptions, useRefreshCompany } from "@/api/companies";
import { ApiError } from "@/api/errors";
import type { CompanyListItem } from "@/api/generated/types.gen";
import type { StatementType } from "@/api/statements";
import { Button } from "@/components/ui/button";
import { CapitalView } from "@/features/capital/CapitalView";
import { CompsView } from "@/features/comps/CompsView";
import { ForecastView } from "@/features/forecast/ForecastView";
import { GuidanceView } from "@/features/guidance/GuidanceView";
import { NotesView } from "@/features/notes/NotesView";
import { Overview } from "@/features/overview/Overview";
import { QualityView } from "@/features/quality/QualityView";
import { RatiosView } from "@/features/ratios/RatiosView";
import { ScenariosView } from "@/features/scenarios/ScenariosView";
import { CASE_PARAM, SCENARIO_PARAM } from "@/features/scenarios/useScenarioParam";
import { SeasonalityView } from "@/features/seasonality/SeasonalityView";
import { SegmentsView } from "@/features/segments/SegmentsView";
import { StatementView } from "@/features/statements/StatementView";
import { ValuationView } from "@/features/valuation/ValuationView";
import { formatCompact, formatPrice, formatRelative } from "@/lib/format";
import { useNow } from "@/lib/now";

const statementTab = (type: StatementType) => (company: CompanyListItem) => (
  <StatementView ticker={company.ticker} cik={company.cik} type={type} />
);

const TABS: { slug: string; label: string; render: (company: CompanyListItem) => ReactNode }[] = [
  { slug: "overview", label: "Overview", render: (company) => <Overview company={company} /> },
  { slug: "income", label: "Income", render: statementTab("IS") },
  { slug: "balance", label: "Balance", render: statementTab("BS") },
  { slug: "cash-flow", label: "Cash Flow", render: statementTab("CF") },
  { slug: "ratios", label: "Ratios", render: (c) => <RatiosView ticker={c.ticker} /> },
  { slug: "quality", label: "Quality", render: (c) => <QualityView ticker={c.ticker} /> },
  { slug: "capital", label: "Capital", render: (c) => <CapitalView ticker={c.ticker} /> },
  { slug: "segments", label: "Segments", render: (c) => <SegmentsView ticker={c.ticker} /> },
  {
    slug: "seasonality",
    label: "Seasonality",
    render: (c) => <SeasonalityView ticker={c.ticker} />,
  },
  { slug: "comps", label: "Comps", render: (c) => <CompsView ticker={c.ticker} /> },
  { slug: "guidance", label: "Guidance", render: (c) => <GuidanceView ticker={c.ticker} /> },
  { slug: "valuation", label: "Valuation", render: (c) => <ValuationView ticker={c.ticker} /> },
  {
    slug: "forecast",
    label: "Forecast",
    render: (c) => <ForecastView ticker={c.ticker} />,
  },
  { slug: "scenarios", label: "Scenarios", render: (c) => <ScenariosView ticker={c.ticker} /> },
  { slug: "notes", label: "Notes", render: (c) => <NotesView ticker={c.ticker} /> },
];

// The tabs that share the picked scenario and case (`?scenario`, `?case`), so moving between them
// keeps both.
const SCENARIO_TABS = new Set(["valuation", "forecast", "scenarios"]);

function tabPath(ticker: string, slug: string, params: URLSearchParams): string {
  if (slug === "overview") return `/c/${ticker}`;
  const shared = new URLSearchParams();
  if (SCENARIO_TABS.has(slug)) {
    for (const name of [SCENARIO_PARAM, CASE_PARAM]) {
      const value = params.get(name);
      if (value) shared.set(name, value);
    }
  }
  const query = shared.size > 0 ? `?${shared}` : "";
  return `/c/${ticker}/${slug}${query}`;
}

const tabClassName = ({ isActive }: { isActive: boolean }) =>
  isActive
    ? "border-foreground text-foreground -mb-px border-b py-2 whitespace-nowrap"
    : "text-muted-foreground hover:text-foreground py-2 whitespace-nowrap";

export function Company() {
  const { ticker = "", tab = "overview" } = useParams<{ ticker: string; tab?: string }>();
  const { data: company, isPending, error } = useQuery(companyQueryOptions(ticker));
  const refresh = useRefreshCompany(ticker);
  const [params] = useSearchParams();
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
          <NavLink
            key={slug}
            to={tabPath(company.ticker, slug, params)}
            end
            className={tabClassName}
          >
            {label}
          </NavLink>
        ))}
      </nav>
      <Fragment key={active.slug}>{active.render(company)}</Fragment>
    </div>
  );
}

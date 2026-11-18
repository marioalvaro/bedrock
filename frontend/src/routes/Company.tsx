import { useQuery } from "@tanstack/react-query";
import { Fragment, type ReactNode } from "react";
import { RefreshCw } from "lucide-react";
import { Link, NavLink, useParams, useSearchParams } from "react-router";

import { companyErrorMessage, companyQueryOptions, useRefreshCompany } from "@/api/companies";
import { ApiError } from "@/api/errors";
import type { CompanyListItem } from "@/api/generated/types.gen";
import type { StatementType } from "@/api/statements";
import { Button } from "@/components/ui/button";
import { BacktestView } from "@/features/backtest/BacktestView";
import { CapitalView } from "@/features/capital/CapitalView";
import { CompsView } from "@/features/comps/CompsView";
import { DataView } from "@/features/data/DataView";
import { FilingsStatus } from "@/features/filings/FilingsStatus";
import { NewFilingMark } from "@/features/filings/NewFilingMark";
import { ForecastView } from "@/features/forecast/ForecastView";
import { GuidanceView } from "@/features/guidance/GuidanceView";
import { NotesView } from "@/features/notes/NotesView";
import { Overview } from "@/features/overview/Overview";
import { QualityView } from "@/features/quality/QualityView";
import { RatiosView } from "@/features/ratios/RatiosView";
import { ReviewView } from "@/features/review/ReviewView";
import { ScenariosView } from "@/features/scenarios/ScenariosView";
import { CASE_PARAM, SCENARIO_PARAM } from "@/features/scenarios/useScenarioParam";
import { SeasonalityView } from "@/features/seasonality/SeasonalityView";
import { SegmentsView } from "@/features/segments/SegmentsView";
import { StatementView } from "@/features/statements/StatementView";
import { CompanySwitcher } from "@/features/switcher/CompanySwitcher";
import { ValuationView } from "@/features/valuation/ValuationView";
import { formatCompact, formatPrice, formatRelative } from "@/lib/format";
import { useNow } from "@/lib/now";

const statementTab = (type: StatementType) => (company: CompanyListItem) => (
  <StatementView ticker={company.ticker} cik={company.cik} type={type} />
);

type Tab = { slug: string; label: string; render: (company: CompanyListItem) => ReactNode };
type TabGroup = { slug: string; label: string; tabs: Tab[] };

// Two levels (FR-WS-05, erd/workspace.md "Navigation"): the groups on the first bar, the active
// group's tabs on the second, in workflow order. Slugs and URLs are flat, so the group is derived
// from the active tab's slug.
const TAB_GROUPS: TabGroup[] = [
  {
    slug: "overview",
    label: "Overview",
    tabs: [{ slug: "overview", label: "Overview", render: (c) => <Overview company={c} /> }],
  },
  {
    slug: "financials",
    label: "Financials",
    tabs: [
      { slug: "income", label: "Income", render: statementTab("IS") },
      { slug: "balance", label: "Balance", render: statementTab("BS") },
      { slug: "cash-flow", label: "Cash Flow", render: statementTab("CF") },
      { slug: "segments", label: "Segments", render: (c) => <SegmentsView ticker={c.ticker} /> },
      { slug: "data", label: "Data", render: (c) => <DataView ticker={c.ticker} /> },
    ],
  },
  {
    slug: "analysis",
    label: "Analysis",
    tabs: [
      { slug: "ratios", label: "Ratios", render: (c) => <RatiosView ticker={c.ticker} /> },
      { slug: "capital", label: "Capital", render: (c) => <CapitalView ticker={c.ticker} /> },
      { slug: "quality", label: "Quality", render: (c) => <QualityView ticker={c.ticker} /> },
      {
        slug: "seasonality",
        label: "Seasonality",
        render: (c) => <SeasonalityView ticker={c.ticker} />,
      },
      { slug: "comps", label: "Comps", render: (c) => <CompsView ticker={c.ticker} /> },
    ],
  },
  {
    // Inputs before outputs: what management says, the drivers, the forecast, the value.
    slug: "model",
    label: "Model",
    tabs: [
      { slug: "guidance", label: "Guidance", render: (c) => <GuidanceView ticker={c.ticker} /> },
      {
        slug: "scenarios",
        label: "Scenarios",
        render: (c) => <ScenariosView ticker={c.ticker} />,
      },
      { slug: "forecast", label: "Forecast", render: (c) => <ForecastView ticker={c.ticker} /> },
      {
        slug: "valuation",
        label: "Valuation",
        render: (c) => <ValuationView ticker={c.ticker} />,
      },
    ],
  },
  {
    // The model scored against what happened.
    slug: "track",
    label: "Track",
    tabs: [
      { slug: "backtest", label: "Backtest", render: (c) => <BacktestView ticker={c.ticker} /> },
      { slug: "review", label: "Review", render: (c) => <ReviewView ticker={c.ticker} /> },
    ],
  },
  {
    slug: "notes",
    label: "Notes",
    tabs: [{ slug: "notes", label: "Notes", render: (c) => <NotesView ticker={c.ticker} /> }],
  },
];

const TABS: Tab[] = TAB_GROUPS.flatMap((group) => group.tabs);

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

/** The company page, remounted per ticker so one company's refresh reply (its snapshot line and
 * warnings) never shows on another's page: React Router keeps the element across `:ticker`. */
export function Company() {
  const { ticker = "" } = useParams<{ ticker: string }>();
  return <CompanyPage key={ticker} />;
}

function CompanyPage() {
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
  const activeGroup = TAB_GROUPS.find((group) => group.tabs.includes(active))!;

  return (
    <div>
      <div className="border-border flex flex-wrap items-baseline gap-x-4 gap-y-1 border-b px-4 py-2">
        <CompanySwitcher ticker={company.ticker} slug={active.slug} />
        <span className="text-muted-foreground">{company.name}</span>
        <span data-testid="header-price" className="num">
          {formatPrice(company.price)}
        </span>
        <span data-testid="header-market-cap" className="num text-muted-foreground">
          {formatCompact(company.market_cap)}
        </span>
        <span className="ml-auto flex flex-wrap items-center gap-2">
          <NewFilingMark filings={company.new_filings} />
          <FilingsStatus company={company} />
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
        {typeof refresh.data?.snapshot_id === "number" && (
          <p className="text-muted-foreground basis-full text-sm">
            Forecast snapshotted before loading the filing.{" "}
            <Link to={`/c/${company.ticker}/review`} className="underline underline-offset-2">
              Review the result
            </Link>
          </p>
        )}
        {refresh.data?.warnings.map((warning) => (
          <p key={warning} className="text-muted-foreground basis-full text-sm">
            {warning}
          </p>
        ))}
      </div>
      <nav
        aria-label="Sections"
        className="border-border flex gap-4 overflow-x-auto border-b px-4 text-sm"
      >
        {TAB_GROUPS.map((group) => {
          const isActive = group === activeGroup;
          // A one-tab group's link is the page itself; a larger group's link is only its section.
          const current = isActive ? (group.tabs.length === 1 ? "page" : "true") : undefined;
          return (
            <Link
              key={group.slug}
              to={tabPath(company.ticker, group.tabs[0]!.slug, params)}
              aria-current={current}
              className={tabClassName({ isActive })}
            >
              {group.label}
            </Link>
          );
        })}
      </nav>
      {activeGroup.tabs.length > 1 && (
        <nav
          aria-label={`${activeGroup.label} tabs`}
          className="border-border flex gap-4 overflow-x-auto border-b px-4 text-xs"
        >
          {activeGroup.tabs.map(({ slug, label }) => (
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
      )}
      <Fragment key={active.slug}>{active.render(company)}</Fragment>
    </div>
  );
}

import { useQuery } from "@tanstack/react-query";
import { Check, ChevronsUpDown } from "lucide-react";
import { useId, useState, type KeyboardEvent } from "react";
import { useNavigate } from "react-router";

import { companiesQueryOptions } from "@/api/companies";
import type { CompanyListItem } from "@/api/generated/types.gen";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

/** The companies whose ticker or name starts with the typed text, ignoring case. */
function matching(companies: CompanyListItem[], typed: string): CompanyListItem[] {
  const prefix = typed.trim().toLowerCase();
  return companies.filter(
    (c) => c.ticker.toLowerCase().startsWith(prefix) || c.name.toLowerCase().startsWith(prefix),
  );
}

/** The company header's ticker (FR-WS-06, erd/workspace.md "Company switcher"): a button that
 * opens the followed companies and moves to another one on the same tab. The query string is
 * dropped: `?scenario` and `?case` name one company's scenario. */
export function CompanySwitcher({ ticker, slug }: { ticker: string; slug: string }) {
  const [open, setOpen] = useState(false);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label="Switch company"
          className="hover:bg-muted focus-visible:ring-ring/50 -mx-1 flex items-center gap-1 rounded-md px-1 outline-none focus-visible:ring-3"
        >
          <h1 className="text-base font-medium">{ticker}</h1>
          <ChevronsUpDown aria-hidden className="text-muted-foreground size-3.5" />
        </button>
      </PopoverTrigger>
      <PopoverContent aria-label="Switch company" align="start" className="p-0">
        {/* Radix unmounts the content when closed, so each opening starts a new filter. */}
        <SwitcherPanel current={ticker} slug={slug} onChosen={() => setOpen(false)} />
      </PopoverContent>
    </Popover>
  );
}

function SwitcherPanel({
  current,
  slug,
  onChosen,
}: {
  current: string;
  slug: string;
  onChosen: () => void;
}) {
  const { data, isPending, isError } = useQuery(companiesQueryOptions);
  const navigate = useNavigate();
  const listId = useId();
  const [typed, setTyped] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const matches = matching(data ?? [], typed);
  const active = matches[Math.min(activeIndex, matches.length - 1)];
  const optionId = (t: string) => `${listId}-${t}`;

  function choose(company: CompanyListItem) {
    onChosen();
    navigate(slug === "overview" ? `/c/${company.ticker}` : `/c/${company.ticker}/${slug}`);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((at) => Math.max(0, Math.min(at + 1, matches.length - 1)));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((at) => Math.max(0, Math.min(at, matches.length - 1) - 1));
    } else if (event.key === "Enter" && active) {
      event.preventDefault();
      choose(active);
    }
  }

  return (
    <div className="text-sm">
      <input
        role="combobox"
        aria-label="Filter companies"
        // The panel exists only while the popover is open, so its list is always expanded.
        aria-expanded
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={active ? optionId(active.ticker) : undefined}
        placeholder="Ticker or name"
        value={typed}
        onChange={(event) => {
          setTyped(event.target.value);
          setActiveIndex(0);
        }}
        onKeyDown={onKeyDown}
        className="border-border placeholder:text-muted-foreground w-full border-b bg-transparent px-3 py-2 outline-none"
      />
      {isPending && <p className="text-muted-foreground px-3 py-2">Loading…</p>}
      {isError && <p className="text-destructive px-3 py-2">Could not load the companies.</p>}
      {data && matches.length === 0 && (
        <p className="text-muted-foreground px-3 py-2">No matching company.</p>
      )}
      {matches.length > 0 && (
        <ul
          id={listId}
          role="listbox"
          aria-label="Companies"
          className="max-h-72 overflow-y-auto p-1"
        >
          {matches.map((company) => (
            <li
              key={company.ticker}
              id={optionId(company.ticker)}
              role="option"
              aria-selected={company === active}
              onClick={() => choose(company)}
              className={
                "flex cursor-pointer items-baseline gap-2 rounded-md px-2 py-1" +
                (company === active ? " bg-muted" : "")
              }
            >
              <span data-testid="option-ticker" className="font-medium">
                {company.ticker}
              </span>
              <span className="text-muted-foreground truncate">{company.name}</span>
              {company.ticker === current && (
                <span className="ml-auto self-center">
                  <Check aria-hidden className="size-3.5" />
                  <span className="sr-only">(current)</span>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

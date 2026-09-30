import { useParams } from "react-router";

const TABS = ["Overview"] as const;

export function Company() {
  const { ticker, tab = "Overview" } = useParams<{ ticker: string; tab?: string }>();

  return (
    <div>
      <div className="border-border flex gap-4 border-b px-4 text-sm">
        {TABS.map((tabName) => (
          <span
            key={tabName}
            className={
              tabName === tab
                ? "border-foreground text-foreground -mb-px border-b py-2"
                : "text-muted-foreground py-2"
            }
          >
            {tabName}
          </span>
        ))}
      </div>
      <p className="text-muted-foreground p-4 text-sm">{ticker} overview arrives in M1.</p>
    </div>
  );
}

import { useQuery } from "@tanstack/react-query";

import { classificationStatusQueryOptions } from "@/api/classification";
import { costText, tokensText } from "@/features/classification/classify";

const usage = (used: number, budget: number) =>
  `${tokensText(used)} of ${tokensText(budget)} tokens`;

/** Settings: which classifiers have a key, and the tokens and money the app has spent (M7d S5). */
export function ClassifierStatus() {
  const { data, isPending, isError } = useQuery(classificationStatusQueryOptions());

  return (
    <section aria-label="Line classifiers">
      <h2 className="mt-8 mb-3 text-lg font-semibold">Line classifiers</h2>
      {isPending && <p className="text-muted-foreground text-sm">Loading…</p>}
      {isError && <p className="text-destructive text-sm">Could not load the classifier status.</p>}
      {data && (
        <div className="space-y-3 text-sm">
          <table aria-label="Classifiers" className="text-left">
            <tbody>
              {data.classifiers.map((classifier) => (
                <tr key={classifier.name} className="border-b">
                  <td className="px-2 py-1">{classifier.name}</td>
                  <td
                    className={`px-2 py-1 ${classifier.configured ? "" : "text-muted-foreground"}`}
                  >
                    {classifier.configured ? "key set" : "no key"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
            <dt className="text-muted-foreground">Used today</dt>
            <dd className="tabular-nums">{usage(data.used_today, data.daily_tokens)}</dd>
            <dt className="text-muted-foreground">Used this month</dt>
            <dd className="tabular-nums">{usage(data.used_month, data.monthly_tokens)}</dd>
            <dt className="text-muted-foreground">Estimated cost this month</dt>
            <dd className="tabular-nums">{costText(data.cost_month_usd)}</dd>
          </dl>
          <p className="text-muted-foreground text-xs">
            Set a spending limit in the provider&apos;s console as well: these budgets only limit
            this app.
          </p>
        </div>
      )}
    </section>
  );
}

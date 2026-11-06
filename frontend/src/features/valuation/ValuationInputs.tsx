import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { compsSetsQueryOptions } from "@/api/context";
import { ApiError } from "@/api/errors";
import type {
  ForecastYearOut,
  ValuationInputIn,
  ValuationInputRowOut,
} from "@/api/generated/types.gen";
import { CASES, type ScenarioCase } from "@/api/scenarios";
import {
  ValuationUnavailable,
  usePutValuationInputs,
  useResetValuationInputs,
  valuationInputsQueryOptions,
} from "@/api/valuation";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import {
  choiceLabel,
  clearText,
  inputEdit,
  inputText,
  resetText,
  shownCodes,
  sourceClass,
  sourceTitle,
  targetFields,
  targets,
} from "./valuationFormat";

const SELECT = "border-input h-8 rounded-lg border bg-transparent px-2 text-sm";
const GROUPS = ["Discount rate", "Terminal value"] as const;
const COMPS_SET = "comps_set_id";

// What an editor needs: send one PUT row, and the error to show under it.
interface FieldContext {
  scenarioCase: ScenarioCase;
  forecastYears: ForecastYearOut[];
  errors: Record<string, string>;
  setError: (code: string, message: string | null) => void;
  send: (row: ValuationInputIn) => void;
  compsSets: { id: number; name: string }[];
}

// A number field: commits on blur; an unchanged text sends nothing (G29: never a stale value).
function NumberEditor({ row, context }: { row: ValuationInputRowOut; context: FieldContext }) {
  const [text, setText] = useState(() => inputText(row));
  const commit = () => {
    const edit = inputEdit(row, text);
    if (edit === "invalid") context.setError(row.code, "Enter a number");
    else if (edit === null) context.setError(row.code, null);
    else context.send(edit);
  };
  return (
    <Input
      aria-label={row.label}
      aria-invalid={row.code in context.errors}
      title={sourceTitle(row)}
      className={cn("num w-28", sourceClass(row.source))}
      value={text}
      onChange={(e) => setText(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
    />
  );
}

function SelectEditor({
  row,
  context,
  options,
}: {
  row: ValuationInputRowOut;
  context: FieldContext;
  options: { value: string; label: string }[];
}) {
  return (
    <select
      aria-label={row.label}
      aria-invalid={row.code in context.errors}
      title={sourceTitle(row)}
      className={cn(SELECT, sourceClass(row.source))}
      value={row.value ?? ""}
      onChange={(e) => context.send({ code: row.code, value: e.target.value || null })}
    >
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

function Editor({ row, context }: { row: ValuationInputRowOut; context: FieldContext }) {
  if (row.kind === "bool") {
    return (
      <label
        className={cn("flex items-center gap-2 text-sm", sourceClass(row.source))}
        title={sourceTitle(row)}
      >
        <input
          type="checkbox"
          checked={row.value === "true"}
          onChange={(e) => context.send({ code: row.code, value: String(e.target.checked) })}
        />
        {row.label}
      </label>
    );
  }
  if (row.kind === "choice") {
    const options = (row.choices ?? []).map((value) => ({ value, label: choiceLabel(value) }));
    return <SelectEditor row={row} context={context} options={options} />;
  }
  if (row.unit === "year") {
    const options = context.forecastYears.map((year) => ({
      value: String(year.index),
      label: year.label,
    }));
    return <SelectEditor row={row} context={context} options={options} />;
  }
  if (row.kind === "comps_set") {
    const options = [
      { value: "", label: "None" },
      ...context.compsSets.map((set) => ({ value: String(set.id), label: set.name })),
    ];
    return <SelectEditor row={row} context={context} options={options} />;
  }
  // Re-mounted when the stored value changes, so the text follows a save or a reset.
  return <NumberEditor key={`${row.source}:${row.value}`} row={row} context={context} />;
}

// An editor with its clear button (own values only) and its error.
function Field({ row, context }: { row: ValuationInputRowOut; context: FieldContext }) {
  const clear = clearText(context.scenarioCase);
  return (
    <div className="space-y-0.5">
      <div className="flex items-center gap-2">
        <Editor row={row} context={context} />
        {row.source === "own" && (
          <Button
            variant="ghost"
            size="sm"
            aria-label={`${row.label}: ${clear}`}
            onClick={() => context.send({ code: row.code, value: null })}
          >
            {clear}
          </Button>
        )}
      </div>
      {context.errors[row.code] && (
        <p className="text-destructive text-xs">{context.errors[row.code]}</p>
      )}
    </div>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section aria-label={title} className="border-border space-y-2 rounded-lg border p-3">
      <h3 className="text-sm font-medium">{title}</h3>
      {children}
    </section>
  );
}

function MultiplesPanel({
  rows,
  context,
}: {
  rows: ValuationInputRowOut[];
  context: FieldContext;
}) {
  const byCode = new Map(rows.map((row) => [row.code, row]));
  const list = targets(rows);
  const peer = list.some(({ code }) => byCode.get(`${code}_source`)?.value === "peer_median");
  const cell = (code: string, shown: boolean) => {
    const row = byCode.get(code);
    return <td className="px-2 py-1">{shown && row && <Field row={row} context={context} />}</td>;
  };
  const compsSet = byCode.get(COMPS_SET);
  return (
    <Panel title="Multiples">
      {peer && compsSet && (
        <div className="flex items-center gap-2 text-sm">
          <span>{compsSet.label}</span>
          <Field row={compsSet} context={context} />
        </div>
      )}
      <table aria-label="Multiple targets" className="text-sm">
        <thead>
          <tr className="text-muted-foreground">
            {["Target", "Source", "Multiple", "Percentile", "Year"].map((name) => (
              <th key={name} scope="col" className="px-2 py-1 text-left font-normal">
                {name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {list.map(({ code, label }) => {
            const fields = targetFields(byCode.get(`${code}_source`)?.value ?? null);
            return (
              <tr key={code}>
                <th scope="row" className="px-2 py-1 text-left font-normal">
                  {label}
                </th>
                {cell(`${code}_source`, true)}
                {cell(`${code}_multiple`, fields.multiple)}
                {cell(`${code}_percentile`, fields.percentile)}
                {cell(`${code}_year`, fields.year)}
              </tr>
            );
          })}
        </tbody>
      </table>
    </Panel>
  );
}

interface ValuationInputsProps {
  ticker: string;
  scenarioId: number;
  scenarioCase: ScenarioCase;
}

/**
 * The picked case's valuation inputs, editable: each value styled by its source (own, inherited
 * from Base, default, derived); one PUT row per change; a case reset behind a dialog.
 */
export function ValuationInputs({ ticker, scenarioId, scenarioCase }: ValuationInputsProps) {
  const { data, isPending, error } = useQuery(
    valuationInputsQueryOptions(ticker, scenarioId, scenarioCase),
  );
  const peer = data?.rows.some(
    (row) => row.code.endsWith("_source") && row.value === "peer_median",
  );
  const { data: sets } = useQuery({ ...compsSetsQueryOptions(ticker), enabled: peer === true });
  const put = usePutValuationInputs(ticker);
  const reset = useResetValuationInputs(ticker);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [resetting, setResetting] = useState(false);
  const caseLabel = CASES.find((c) => c.value === scenarioCase)?.label ?? scenarioCase;

  if (isPending) return <p className="text-muted-foreground p-4 text-sm">Loading…</p>;
  if (!data) {
    return (
      <p className="text-destructive p-4 text-sm">
        {(error instanceof ValuationUnavailable && error.detail) ||
          "Could not load the valuation inputs."}
      </p>
    );
  }

  const setError = (code: string, message: string | null) =>
    setErrors((current) => {
      const { [code]: _dropped, ...rest } = current;
      return message === null ? rest : { ...rest, [code]: message };
    });
  const context: FieldContext = {
    scenarioCase,
    forecastYears: data.forecast_years,
    errors,
    setError,
    compsSets: sets ?? [],
    send: (row) =>
      put.mutate(
        { id: scenarioId, case: scenarioCase, rows: [row] },
        {
          onSuccess: () => setError(row.code, null),
          onError: (error) =>
            setError(
              row.code,
              (error instanceof ApiError && error.detail) || "Could not save the input.",
            ),
        },
      ),
  };
  const shown = shownCodes(data.rows);

  return (
    <section aria-label="Inputs" className="space-y-3">
      <div className="flex items-center gap-2">
        <h2 className="text-base font-semibold">Inputs</h2>
        <Button variant="outline" size="sm" onClick={() => setResetting(true)}>
          Reset {caseLabel} inputs
        </Button>
        {reset.isError && (
          <p className="text-destructive text-sm">
            {(reset.error instanceof ApiError && reset.error.detail) ||
              "Could not reset the inputs."}
          </p>
        )}
      </div>
      {data.warnings.map((warning) => (
        <p key={warning} className="text-muted-foreground text-sm">
          {warning}
        </p>
      ))}
      <div className="grid gap-3 md:grid-cols-2">
        {GROUPS.map((group) => (
          <Panel key={group} title={group}>
            {data.rows
              .filter((row) => row.group === group && shown.has(row.code))
              .map((row) => (
                <div key={row.code} className="flex flex-wrap items-start gap-2 text-sm">
                  {row.kind !== "bool" && <span className="w-40 pt-1.5">{row.label}</span>}
                  <Field row={row} context={context} />
                </div>
              ))}
          </Panel>
        ))}
      </div>
      <MultiplesPanel
        rows={data.rows.filter((row) => row.group === "Multiples")}
        context={context}
      />
      <AlertDialog open={resetting} onOpenChange={setResetting}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Reset {caseLabel} inputs?</AlertDialogTitle>
            <AlertDialogDescription>{resetText(scenarioCase)}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={() => reset.mutate({ id: scenarioId, case: scenarioCase })}>
              Reset
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}

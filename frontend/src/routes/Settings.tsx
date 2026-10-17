import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { qoeRulesQueryOptions, useResetQoeThresholds, useSetQoeThresholds } from "@/api/analysis";
import { companyErrorMessage } from "@/api/companies";
import type { QoeRuleOut } from "@/api/generated/types.gen";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { parseThreshold, toThresholdText } from "@/lib/format";

const toText = (level: string | null, unit: QoeRuleOut["unit"]) =>
  level === null ? "" : toThresholdText(level, unit as "pct" | "x");

function RuleRow({ rule }: { rule: QoeRuleOut }) {
  const unit = rule.unit as "pct" | "x";
  const [warn, setWarn] = useState(toText(rule.warn, unit));
  const [alert, setAlert] = useState(toText(rule.alert, unit));
  const [parseError, setParseError] = useState<string | null>(null);
  const save = useSetQoeThresholds();
  const reset = useResetQoeThresholds();
  const suffix = unit === "pct" ? "%" : "x";

  // Blank is "no level"; null from parseThreshold on non-blank text is malformed.
  const level = (text: string): { ok: boolean; value: string | null } => {
    if (text.trim() === "") return { ok: true, value: null };
    const value = parseThreshold(text, unit);
    return { ok: value !== null, value };
  };

  function onSave() {
    const w = level(warn);
    const a = level(alert);
    if (!w.ok || !a.ok) {
      setParseError("Enter a number");
      return;
    }
    setParseError(null);
    reset.reset();
    save.mutate({ code: rule.code, body: { warn: w.value, alert: a.value } });
  }

  function onReset() {
    setParseError(null);
    save.reset();
    reset.mutate(rule.code);
  }

  const error =
    parseError ??
    (save.isError ? companyErrorMessage(save.error, "Could not save the thresholds.") : null) ??
    (reset.isError ? companyErrorMessage(reset.error, "Could not reset the thresholds.") : null);

  const levelInput = (name: string, value: string, set: (v: string) => void) => (
    <td className="px-2 py-2">
      <div className="flex items-center gap-1">
        <Input
          aria-label={`${rule.label} ${name}`}
          className="h-8 w-20"
          inputMode="decimal"
          value={value}
          onChange={(e) => set(e.target.value)}
        />
        <span className="text-muted-foreground text-sm">{suffix}</span>
      </div>
    </td>
  );

  return (
    <tr className="border-b align-top">
      <td className="px-2 py-2 text-sm">{rule.label}</td>
      <td className="text-muted-foreground px-2 py-2 text-sm">{rule.rule}</td>
      <td className="px-2 py-2 text-sm">{rule.direction}</td>
      {levelInput("warn", warn, setWarn)}
      {levelInput("alert", alert, setAlert)}
      <td className="px-2 py-2">
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            aria-label={`Save ${rule.label}`}
            disabled={save.isPending}
            onClick={onSave}
          >
            Save
          </Button>
          {rule.overridden && (
            <Button
              size="sm"
              variant="outline"
              aria-label={`Reset ${rule.label}`}
              disabled={reset.isPending}
              onClick={onReset}
            >
              Reset
            </Button>
          )}
        </div>
        {error && (
          <p role="alert" className="text-destructive mt-1 text-xs">
            {error}
          </p>
        )}
      </td>
    </tr>
  );
}

function QoeThresholds() {
  const rules = useQuery(qoeRulesQueryOptions());
  if (rules.isPending) return <p className="text-muted-foreground text-sm">Loading…</p>;
  if (rules.isError)
    return <p className="text-destructive text-sm">Could not load the thresholds.</p>;
  if (rules.data.length === 0) return <p className="text-muted-foreground text-sm">No rules.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left">
        <thead>
          <tr className="text-muted-foreground border-b text-xs">
            <th className="px-2 py-1 font-medium">Label</th>
            <th className="px-2 py-1 font-medium">Rule</th>
            <th className="px-2 py-1 font-medium">Direction</th>
            <th className="px-2 py-1 font-medium">Warn</th>
            <th className="px-2 py-1 font-medium">Alert</th>
            <th className="px-2 py-1 font-medium">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rules.data.map((rule) => (
            // Keyed by the server values so drafts re-sync after a save/reset refetch.
            <RuleRow
              key={`${rule.code}|${rule.warn}|${rule.alert}|${rule.overridden}`}
              rule={rule}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Settings() {
  return (
    <div className="p-4">
      <div className="flex items-center justify-between">
        <span className="text-sm">Theme</span>
        <ThemeToggle />
      </div>
      <h2 className="mt-8 mb-3 text-lg font-semibold">Quality-of-earnings thresholds</h2>
      <QoeThresholds />
    </div>
  );
}

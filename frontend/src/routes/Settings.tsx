import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { qoeRulesQueryOptions, useResetQoeThresholds, useSetQoeThresholds } from "@/api/analysis";
import { companyErrorMessage } from "@/api/companies";
import type { QoeRuleOut } from "@/api/generated/types.gen";
import { ThemeToggle } from "@/components/ThemeToggle";
import { CustomRules } from "@/features/settings/CustomRules";
import { FormulaReference } from "@/features/settings/FormulaReference";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { FORMULA_UNITS_NOTE, isFormulaLevel, levelText, levelToSend } from "@/lib/levels";

function RuleRow({ rule }: { rule: QoeRuleOut }) {
  const unit = rule.unit as "pct" | "x";
  const [warn, setWarn] = useState(levelText(rule.warn, rule.warn_formula, unit));
  const [alert, setAlert] = useState(levelText(rule.alert, rule.alert_formula, unit));
  const save = useSetQoeThresholds();
  const reset = useResetQoeThresholds();
  const suffix = unit === "pct" ? "%" : "x";

  function onSave() {
    reset.reset();
    save.mutate({
      code: rule.code,
      body: { warn: levelToSend(warn, unit), alert: levelToSend(alert, unit) },
    });
  }

  function onReset() {
    save.reset();
    reset.mutate(rule.code);
  }

  const error =
    (save.isError ? companyErrorMessage(save.error, "Could not save the thresholds.") : null) ??
    (reset.isError ? companyErrorMessage(reset.error, "Could not reset the thresholds.") : null) ??
    rule.error;

  const levelInput = (name: string, value: string, set: (v: string) => void) => (
    <td className="px-2 py-2">
      <div className="flex items-center gap-1">
        <Input
          aria-label={`${rule.label} ${name}`}
          className={isFormulaLevel(value, unit) ? "h-8 w-40" : "h-8 w-20"}
          inputMode="decimal"
          value={value}
          onChange={(e) => set(e.target.value)}
        />
        {isFormulaLevel(value, unit) ? (
          <span aria-label="formula" title="formula" className="text-muted-foreground text-sm">
            ƒ
          </span>
        ) : (
          <span className="text-muted-foreground text-sm">{suffix}</span>
        )}
      </div>
      {isFormulaLevel(value, unit) && (
        <p className="text-muted-foreground mt-1 max-w-40 text-xs">{FORMULA_UNITS_NOTE}</p>
      )}
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
  const builtIns = rules.data.filter((rule) => !rule.custom);
  if (builtIns.length === 0) return <p className="text-muted-foreground text-sm">No rules.</p>;
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
          {builtIns.map((rule) => (
            // Keyed by the server values so drafts re-sync after a save/reset refetch.
            <RuleRow
              key={`${rule.code}|${rule.warn}|${rule.alert}|${rule.warn_formula}|${rule.alert_formula}|${rule.overridden}`}
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
      <CustomRules />
      <FormulaReference />
    </div>
  );
}

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import {
  customRulesQueryOptions,
  useCreateQoeCustomRule,
  useDeleteQoeCustomRule,
  useUpdateQoeCustomRule,
} from "@/api/analysis";
import { companyErrorMessage } from "@/api/companies";
import type { QoeCustomRuleIn, QoeCustomRuleOut } from "@/api/generated/types.gen";
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
import { Label } from "@/components/ui/label";
import { formatThreshold, type ThresholdUnit } from "@/lib/format";
import {
  FORMULA_HINT,
  FORMULA_UNITS_NOTE,
  isFormulaLevel,
  levelText,
  levelToSend,
} from "@/lib/levels";

const SELECT_CLASS = "border-input h-8 w-full rounded-lg border bg-transparent px-2 text-sm";

/** "warn > 5% · alert > 10%"; a formula level shows its text as is; "—" when there is no level. */
function levelsSummary(rule: QoeCustomRuleOut): string {
  const unit = rule.unit as ThresholdUnit;
  const op = rule.direction === "below" ? "<" : ">";
  const parts: string[] = [];
  for (const [name, num, formula] of [
    ["warn", rule.warn, rule.warn_formula],
    ["alert", rule.alert, rule.alert_formula],
  ] as const) {
    if (formula !== null) parts.push(`${name} ${op} ${formula}`);
    else if (num !== null) parts.push(`${name} ${op} ${formatThreshold(num, unit)}`);
  }
  return parts.length === 0 ? "—" : parts.join(" · ");
}

function LevelInput({
  id,
  name,
  value,
  unit,
  onChange,
}: {
  id: string;
  name: string;
  value: string;
  unit: ThresholdUnit;
  onChange: (value: string) => void;
}) {
  return (
    <div className="min-w-0 flex-1 space-y-1">
      <Label htmlFor={id}>{name}</Label>
      <div className="flex items-center gap-1">
        <Input id={id} value={value} onChange={(e) => onChange(e.target.value)} />
        {isFormulaLevel(value, unit) ? (
          <span title="Formula" className="text-muted-foreground text-xs">
            ƒ
          </span>
        ) : (
          <span className="text-muted-foreground text-xs">{unit === "pct" ? "%" : "x"}</span>
        )}
      </div>
    </div>
  );
}

/**
 * Add/edit form. Changing the unit while editing keeps the typed level text as is (no
 * re-derivation), so the user sees and controls exactly what is sent.
 */
function RuleForm({ editing, onDone }: { editing: QoeCustomRuleOut | null; onDone: () => void }) {
  const create = useCreateQoeCustomRule();
  const update = useUpdateQoeCustomRule();
  const initialUnit = (editing?.unit ?? "pct") as ThresholdUnit;
  const [label, setLabel] = useState(editing?.label ?? "");
  const [formula, setFormula] = useState(editing?.formula ?? "");
  const [direction, setDirection] = useState<QoeCustomRuleIn["direction"]>(
    (editing?.direction ?? "above") as QoeCustomRuleIn["direction"],
  );
  const [unit, setUnit] = useState<ThresholdUnit>(initialUnit);
  const [warn, setWarn] = useState(
    editing ? levelText(editing.warn, editing.warn_formula, initialUnit) : "",
  );
  const [alertText, setAlertText] = useState(
    editing ? levelText(editing.alert, editing.alert_formula, initialUnit) : "",
  );
  const [error, setError] = useState<string | null>(null);
  const pending = create.isPending || update.isPending;

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (label.trim() === "") return setError("Enter a label");
    if (formula.trim() === "") return setError("Enter a formula");
    setError(null);
    const body: QoeCustomRuleIn = {
      label: label.trim(),
      formula: formula.trim(),
      direction,
      unit,
      warn: levelToSend(warn, unit),
      alert: levelToSend(alertText, unit),
    };
    const options = {
      onSuccess: onDone,
      onError: (e: Error) => setError(companyErrorMessage(e, "Could not save the rule.")),
    };
    if (editing) update.mutate({ id: editing.id, body }, options);
    else create.mutate(body, options);
  }

  return (
    <form onSubmit={submit} className="space-y-2" noValidate>
      <div className="space-y-1">
        <Label htmlFor="cr-label">Label</Label>
        <Input id="cr-label" value={label} onChange={(e) => setLabel(e.target.value)} />
      </div>
      <div className="space-y-1">
        <Label htmlFor="cr-formula">Formula</Label>
        <Input
          id="cr-formula"
          className="font-mono"
          value={formula}
          onChange={(e) => setFormula(e.target.value)}
        />
      </div>
      <div className="flex flex-wrap gap-2">
        <div className="min-w-0 flex-1 space-y-1">
          <Label htmlFor="cr-direction">Direction</Label>
          <select
            id="cr-direction"
            value={direction}
            onChange={(e) => setDirection(e.target.value as QoeCustomRuleIn["direction"])}
            className={SELECT_CLASS}
          >
            <option value="above">Above</option>
            <option value="below">Below</option>
          </select>
        </div>
        <div className="min-w-0 flex-1 space-y-1">
          <Label htmlFor="cr-unit">Unit</Label>
          <select
            id="cr-unit"
            value={unit}
            onChange={(e) => setUnit(e.target.value as ThresholdUnit)}
            className={SELECT_CLASS}
          >
            <option value="pct">pct</option>
            <option value="x">x</option>
          </select>
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        <LevelInput id="cr-warn" name="Warn" value={warn} unit={unit} onChange={setWarn} />
        <LevelInput
          id="cr-alert"
          name="Alert"
          value={alertText}
          unit={unit}
          onChange={setAlertText}
        />
      </div>
      {(isFormulaLevel(warn, unit) || isFormulaLevel(alertText, unit)) && (
        <p className="text-muted-foreground text-xs">{FORMULA_UNITS_NOTE}</p>
      )}
      {error && (
        <p role="alert" className="text-destructive text-xs">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={pending}>
          Save
        </Button>
        <Button type="button" size="sm" variant="outline" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

/** Settings, "Custom rules": the list with Edit and Delete (alert-dialog) and an add/edit form. */
export function CustomRules() {
  const { data: rules, isPending, isError } = useQuery(customRulesQueryOptions());
  const remove = useDeleteQoeCustomRule();
  // `null` closed, "new" adding, otherwise the rule being edited.
  const [form, setForm] = useState<QoeCustomRuleOut | "new" | null>(null);
  const [toDelete, setToDelete] = useState<QoeCustomRuleOut | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium">Custom rules</h2>
        {form === null && (
          <Button type="button" size="sm" variant="outline" onClick={() => setForm("new")}>
            Add rule
          </Button>
        )}
      </div>
      {isPending ? (
        <p className="text-muted-foreground text-sm">Loading…</p>
      ) : isError ? (
        <p className="text-destructive text-sm">Could not load the custom rules.</p>
      ) : rules.length === 0 ? (
        <p className="text-muted-foreground text-sm">No custom rules.</p>
      ) : (
        <ul className="space-y-2">
          {rules.map((rule) => (
            <li key={rule.id} className="border-border space-y-1 border-b pb-2 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span>{rule.label}</span>
                <span className="text-muted-foreground text-xs">{`${rule.direction} · ${rule.unit}`}</span>
                <span className="ml-auto inline-flex gap-1">
                  <Button
                    type="button"
                    size="xs"
                    variant="outline"
                    aria-label={`Edit ${rule.label}`}
                    onClick={() => setForm(rule)}
                  >
                    Edit
                  </Button>
                  <Button
                    type="button"
                    size="xs"
                    variant="outline"
                    aria-label={`Delete ${rule.label}`}
                    onClick={() => {
                      setDeleteError(null);
                      setToDelete(rule);
                    }}
                  >
                    Delete
                  </Button>
                </span>
              </div>
              <div className="text-muted-foreground font-mono text-xs break-words">
                {rule.formula}
              </div>
              <div className="num text-xs">{levelsSummary(rule)}</div>
              {rule.error !== null && <div className="text-destructive text-xs">{rule.error}</div>}
            </li>
          ))}
        </ul>
      )}
      {deleteError && (
        <p role="alert" className="text-destructive text-xs">
          {deleteError}
        </p>
      )}
      {form !== null && (
        <RuleForm
          key={form === "new" ? "new" : form.id}
          editing={form === "new" ? null : form}
          onDone={() => setForm(null)}
        />
      )}
      <p className="text-muted-foreground text-xs">{FORMULA_HINT}</p>
      <AlertDialog open={toDelete !== null} onOpenChange={(open) => !open && setToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this rule?</AlertDialogTitle>
            <AlertDialogDescription>{toDelete?.label}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (toDelete) {
                  const id = toDelete.id;
                  remove.mutate(id, {
                    onSuccess: () =>
                      setForm((f) => (f !== null && f !== "new" && f.id === id ? null : f)),
                    onError: (e) =>
                      setDeleteError(companyErrorMessage(e, "Could not delete the rule.")),
                  });
                }
              }}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}

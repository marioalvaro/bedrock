import type { ClassificationStatusOut, EstimateOut } from "@/api/generated/types.gen";
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

import { costText, estimateText, providerName, tokensLeft, tokensText } from "./classify";

interface ConfirmRunDialogProps {
  open: boolean;
  classifier: string;
  lines: number; // `to_ask`: what Confirm posts as `confirm_lines`
  estimate: EstimateOut | null;
  status: ClassificationStatusOut;
  onConfirm: () => void;
  onCancel: () => void;
}

/** The only way to start a run (principle 3): what it sends, to whom, and what it may cost. */
export function ConfirmRunDialog({
  open,
  classifier,
  lines,
  estimate,
  status,
  onConfirm,
  onCancel,
}: ConfirmRunDialogProps) {
  const left = tokensLeft(status);
  const fields: [string, string][] = [
    ["Lines", String(lines)],
    ["Classifier", classifier],
    ["Estimated tokens", estimate ? estimateText(estimate) : "—"],
    ["Estimated cost", estimate ? costText(estimate.cost_usd) : "—"],
    ["Tokens left today", tokensText(left.today)],
    ["Tokens left this month", tokensText(left.month)],
  ];
  return (
    <AlertDialog open={open} onOpenChange={(next) => !next && onCancel()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Classify {lines} lines?</AlertDialogTitle>
          <AlertDialogDescription>
            This sends the lines&apos; labels, tags and amounts to {providerName(classifier)}.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          {fields.map(([name, value]) => (
            <div key={name} className="contents">
              <dt className="text-muted-foreground">{name}</dt>
              <dd className="tabular-nums">{value}</dd>
            </div>
          ))}
        </dl>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction onClick={onConfirm}>Confirm</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

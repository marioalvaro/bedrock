import { Upload } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useScale } from "@/lib/scale";

import { StatementImportSheet } from "./StatementImportSheet";

/** "Import" and the sheet it opens; the statement tabs and the Overview both place it. */
export function ImportButton({ ticker }: { ticker: string }) {
  const [open, setOpen] = useState(false);
  const scale = useScale();
  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        <Upload /> Import
      </Button>
      <StatementImportSheet
        ticker={ticker}
        open={open}
        scale={scale}
        onClose={() => setOpen(false)}
      />
    </>
  );
}

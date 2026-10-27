export function ProvenanceLegend() {
  return (
    <p className="text-muted-foreground flex flex-wrap gap-x-4 text-xs">
      <span>Reported: as filed</span>
      <span className="prov-derived">Derived: Q4, YTD differences and formulas</span>
      <span className="prov-derived">
        ~ Approximated: rebuilt Q4 share counts and EPS, cover-page share counts
      </span>
      <span className="prov-imported">Imported: from your file, where SEC has no value</span>
      <span>Inferred 0: a rule concluded the line is exactly 0</span>
      <span className="prov-normalized">Normalized: with your adjustments</span>
    </p>
  );
}

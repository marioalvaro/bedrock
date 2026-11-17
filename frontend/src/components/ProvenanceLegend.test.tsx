import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ProvenanceLegend } from "./ProvenanceLegend";

describe("ProvenanceLegend", () => {
  it("explains forecast values in the Forecast tab, in their own style", () => {
    render(<ProvenanceLegend forecast />);

    expect(screen.getByText("Forecast: built from the scenario's drivers")).toHaveClass(
      "prov-forecast",
      "cell-forecast",
    );
  });

  it("leaves the forecast line out of the statement tabs", () => {
    render(<ProvenanceLegend />);

    expect(screen.getByText("Reported: as filed")).toBeInTheDocument();
    expect(screen.queryByText(/^Forecast:/)).toBeNull();
  });

  it("names the AI classified mark (M7d S5)", () => {
    render(<ProvenanceLegend />);

    const entry = screen.getByText("AI classified: filled from a line a classifier placed");
    expect(entry.querySelector(".classified-mark")).not.toBeNull();
  });
});

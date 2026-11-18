import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { NewFilingOut } from "@/api/generated/types.gen";

import { NewFilingMark } from "./NewFilingMark";

const filing = (overrides: Partial<NewFilingOut> = {}): NewFilingOut => ({
  form: "10-Q",
  filed_at: "2026-08-01",
  period_end: "2026-06-27",
  ...overrides,
});

describe("NewFilingMark", () => {
  it("shows nothing when no filing is pending", () => {
    const { container } = render(<NewFilingMark filings={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("names the newest pending filing, with what a refresh does", () => {
    render(<NewFilingMark filings={[filing()]} />);
    const mark = screen.getByText("10-Q filed Aug 1");
    expect(mark.closest("[title]")).toHaveAttribute(
      "title",
      "Refresh to load it. The forecast is snapshotted first.",
    );
    expect(mark.closest("[title]")).toHaveClass("text-prov-derived");
    expect(screen.queryByText(/^\+/)).not.toBeInTheDocument();
  });

  it("counts the other pending filings", () => {
    render(
      <NewFilingMark
        filings={[filing({ form: "10-K", filed_at: "2026-10-31" }), filing(), filing()]}
      />,
    );
    expect(screen.getByText("10-K filed Oct 31")).toBeInTheDocument();
    expect(screen.getByText("+2")).toBeInTheDocument();
  });
});

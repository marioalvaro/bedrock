import { describe, expect, it } from "vitest";

import { companiesQueryOptions, companyQueryOptions } from "./companies";

// The backend refreshes prices hourly in US market hours, so an open page polls for the header
// price and the list's prices (the poll pauses while the tab is in the background).
describe("company queries", () => {
  it("poll for the scheduled price refresh every 15 minutes", () => {
    expect(companyQueryOptions("AAPL").refetchInterval).toBe(15 * 60_000);
    expect(companiesQueryOptions.refetchInterval).toBe(15 * 60_000);
  });
});

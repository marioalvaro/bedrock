import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createSetApiV1CompaniesTickerCompsSetsPost,
  deleteSetApiV1CompaniesTickerCompsSetsSetIdDelete,
  getCompaniesApiV1CompaniesGet,
  getComparisonApiV1CompaniesTickerCompsSetsSetIdComparisonGet,
  getPeerSuggestionsApiV1CompaniesTickerPeerSuggestionsGet,
  listSetsApiV1CompaniesTickerCompsSetsGet,
  updateSetApiV1CompaniesTickerCompsSetsSetIdPut,
} from "@/api/generated/sdk.gen";
import { createQueryClient } from "@/lib/query-client";
import { companyItem } from "@/test/companies";
import { comparison, compsRow, compsSets, peerSuggestions } from "@/test/context";
import { errorResult, okResult } from "@/test/responses";

import { CompsView } from "./CompsView";

vi.mock("@/api/generated/sdk.gen", () => ({
  getCompaniesApiV1CompaniesGet: vi.fn(),
  listSetsApiV1CompaniesTickerCompsSetsGet: vi.fn(),
  createSetApiV1CompaniesTickerCompsSetsPost: vi.fn(),
  updateSetApiV1CompaniesTickerCompsSetsSetIdPut: vi.fn(),
  deleteSetApiV1CompaniesTickerCompsSetsSetIdDelete: vi.fn(),
  getComparisonApiV1CompaniesTickerCompsSetsSetIdComparisonGet: vi.fn(),
  getPeerSuggestionsApiV1CompaniesTickerPeerSuggestionsGet: vi.fn(),
}));

const listCompanies = vi.mocked(getCompaniesApiV1CompaniesGet);
const listSets = vi.mocked(listSetsApiV1CompaniesTickerCompsSetsGet);
const createSet = vi.mocked(createSetApiV1CompaniesTickerCompsSetsPost);
const updateSet = vi.mocked(updateSetApiV1CompaniesTickerCompsSetsSetIdPut);
const deleteSet = vi.mocked(deleteSetApiV1CompaniesTickerCompsSetsSetIdDelete);
const getComparison = vi.mocked(getComparisonApiV1CompaniesTickerCompsSetsSetIdComparisonGet);
const getSuggestions = vi.mocked(getPeerSuggestionsApiV1CompaniesTickerPeerSuggestionsGet);

function renderView() {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  render(
    <QueryClientProvider client={queryClient}>
      <CompsView ticker="AAPL" />
    </QueryClientProvider>,
  );
}

async function renderLoaded() {
  renderView();
  await waitFor(() => expect(cell("pe", "target")).not.toBeNull());
}

const cell = (row: string, column: string) =>
  document.querySelector(`[row-id="${row}"] [col-id="${column}"]`) as HTMLElement;
const addPeer = () => screen.getByRole("combobox", { name: "Add peer" });

beforeEach(() => {
  listCompanies.mockResolvedValue(
    okResult([
      companyItem(),
      companyItem({ id: 2, ticker: "COST", name: "Costco Wholesale Corp", sic: "5331" }),
      companyItem({ id: 3, ticker: "DE", name: "Deere & Co", sic: "3523" }),
      companyItem({ id: 4, ticker: "MSFT", name: "Microsoft Corp", sic: "7372" }),
    ]) as never,
  );
  listSets.mockResolvedValue(okResult(compsSets()) as never);
  getComparison.mockResolvedValue(okResult(comparison()) as never);
  getSuggestions.mockResolvedValue(
    okResult(peerSuggestions().map((s) => ({ ...s, in_set: false }))) as never,
  );
  createSet.mockResolvedValue(okResult({ id: 7, name: "New", members: [] }, 201) as never);
  updateSet.mockResolvedValue(okResult(compsSets()[0]) as never);
  deleteSet.mockResolvedValue(okResult(null, 204) as never);
});

afterEach(() => vi.clearAllMocks());

describe("CompsView sets", () => {
  it("shows Loading… while the sets are pending", async () => {
    listSets.mockReturnValue(new Promise(() => {}) as never);
    renderView();
    expect(await screen.findByText("Loading…")).toBeVisible();
  });

  it("shows an error when the sets cannot load", async () => {
    listSets.mockResolvedValue(errorResult(500) as never);
    renderView();
    expect(await screen.findByText("Could not load the comps sets.")).toBeVisible();
    expect(getComparison).not.toHaveBeenCalled();
  });

  it("shows an empty state with New comps set when there is no set", async () => {
    listSets.mockResolvedValue(okResult([]) as never);
    renderView();
    expect(await screen.findByText("No comps sets yet.")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "New comps set" }));
    await userEvent.type(screen.getByLabelText("Name"), "Hardware & industrials");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(createSet).toHaveBeenCalledWith({
        path: { ticker: "AAPL" },
        body: { name: "Hardware & industrials", members: [] },
      }),
    );
    expect(getComparison).not.toHaveBeenCalled();
  });

  it("picks the first set and lists its members as chips", async () => {
    await renderLoaded();
    const picker = screen.getByRole("combobox", { name: "Comps set" });
    expect(picker).toHaveValue("1");
    expect(screen.getByRole("button", { name: "Remove COST" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Remove DE" })).toBeVisible();
    expect(getComparison).toHaveBeenCalledWith({
      path: { ticker: "AAPL", set_id: 1 },
      query: { basis: "reported" },
    });
  });

  it("switches the comparison and the suggestions with the picker", async () => {
    await renderLoaded();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Comps set" }), "2");
    await waitFor(() =>
      expect(getComparison).toHaveBeenLastCalledWith({
        path: { ticker: "AAPL", set_id: 2 },
        query: { basis: "reported" },
      }),
    );
    expect(getSuggestions).toHaveBeenLastCalledWith({
      path: { ticker: "AAPL" },
      query: { set_id: 2 },
    });
    expect(screen.getByRole("button", { name: "Remove MSFT" })).toBeVisible();
  });

  it("offers the suggested peers first, labelled with the match", async () => {
    await renderLoaded();
    await userEvent.click(screen.getByRole("button", { name: "Remove DE" }));
    const groups = within(addPeer()).getAllByRole("group");
    expect(groups.map((g) => g.getAttribute("label"))).toEqual(["Suggested", "Other followed"]);
    expect(within(groups[0]!).getByRole("option", { name: "DE · major group 35" })).toBeVisible();
    // the company itself and the current members are not offered
    const others = within(groups[1]!)
      .getAllByRole("option")
      .map((o) => o.textContent);
    expect(others).toEqual(["MSFT · Microsoft Corp"]);
  });

  it("adds a peer and saves the member tickers", async () => {
    await renderLoaded();
    await userEvent.selectOptions(addPeer(), "MSFT");
    expect(screen.getByRole("button", { name: "Remove MSFT" })).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Save members" }));
    await waitFor(() =>
      expect(updateSet).toHaveBeenCalledWith({
        path: { ticker: "AAPL", set_id: 1 },
        body: { name: "Hardware & industrials", members: ["COST", "DE", "MSFT"] },
      }),
    );
  });

  it("removes a peer and saves", async () => {
    await renderLoaded();
    await userEvent.click(screen.getByRole("button", { name: "Remove COST" }));
    await userEvent.click(screen.getByRole("button", { name: "Save members" }));
    await waitFor(() =>
      expect(updateSet).toHaveBeenCalledWith({
        path: { ticker: "AAPL", set_id: 1 },
        body: { name: "Hardware & industrials", members: ["DE"] },
      }),
    );
  });

  it("keeps Save members disabled while nothing changed", async () => {
    await renderLoaded();
    expect(screen.getByRole("button", { name: "Save members" })).toBeDisabled();
  });

  it("shows a 422 detail when saving fails", async () => {
    updateSet.mockResolvedValue(errorResult(422, { detail: "Unknown peer: XYZ" }) as never);
    await renderLoaded();
    await userEvent.selectOptions(addPeer(), "MSFT");
    await userEvent.click(screen.getByRole("button", { name: "Save members" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Unknown peer: XYZ");
  });

  it("renames a set with its members kept", async () => {
    await renderLoaded();
    await userEvent.click(screen.getByRole("button", { name: "Rename" }));
    const name = screen.getByLabelText("Name");
    expect(name).toHaveValue("Hardware & industrials");
    await userEvent.clear(name);
    await userEvent.type(name, "Hardware");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(updateSet).toHaveBeenCalledWith({
        path: { ticker: "AAPL", set_id: 1 },
        body: { name: "Hardware", members: ["COST", "DE"] },
      }),
    );
  });

  it("refuses a blank name", async () => {
    await renderLoaded();
    await userEvent.click(screen.getByRole("button", { name: "New" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a name");
    expect(createSet).not.toHaveBeenCalled();
  });

  it("selects a new set once created", async () => {
    await renderLoaded();
    listSets.mockResolvedValue(
      okResult([...compsSets(), { id: 7, name: "New", members: [] }]) as never,
    );
    await userEvent.click(screen.getByRole("button", { name: "New" }));
    await userEvent.type(screen.getByLabelText("Name"), "New");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: "Comps set" })).toHaveValue("7"),
    );
  });

  it("deletes a set behind a confirmation", async () => {
    await renderLoaded();
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Hardware & industrials");
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() =>
      expect(deleteSet).toHaveBeenCalledWith({ path: { ticker: "AAPL", set_id: 1 } }),
    );
  });
});

describe("CompsView comparison", () => {
  it("has a heading row per category and a column per company", async () => {
    await renderLoaded();
    expect(document.querySelector('[row-id="category:Valuation"]')).not.toBeNull();
    expect(document.querySelector('[row-id="category:Profitability"]')).not.toBeNull();
    for (const header of ["AAPL", "COST", "DE", "Peer median", "Peer range", "vs median", "Rank"]) {
      expect(screen.getByRole("columnheader", { name: header })).toBeVisible();
    }
  });

  it("formats the cells by unit", async () => {
    await renderLoaded();
    expect(cell("pe", "target")).toHaveTextContent("34.2x");
    expect(cell("pe", "peer:COST")).toHaveTextContent("52.1x");
    expect(cell("pe", "median")).toHaveTextContent("34.2x");
    expect(cell("pe", "range")).toHaveTextContent("16.3x – 52.1x");
    expect(cell("gross_margin", "target")).toHaveTextContent("46.2%");
    expect(cell("gross_margin", "range")).toHaveTextContent("12.6% – 37.0%");
  });

  it("shows vs median as a percent for x and in points for pct", async () => {
    await renderLoaded();
    expect(cell("pe", "vs")).toHaveTextContent("+12.3%");
    expect(cell("ev_ebitda", "vs")).toHaveTextContent("-21.2%");
    expect(cell("gross_margin", "vs")).toHaveTextContent("+21.4 pts");
  });

  it("shows the rank out of the target and the peers used", async () => {
    await renderLoaded();
    expect(cell("pe", "rank")).toHaveTextContent("2 / 3");
    expect(cell("ev_ebitda", "rank")).toHaveTextContent("2 / 2");
  });

  it("hides the rank when no peer value was used", async () => {
    getComparison.mockResolvedValue(
      okResult(
        comparison({
          rows: [compsRow({ peers: [null, null], n: 0, peer_median: null, target_rank: 1 })],
        }),
      ) as never,
    );
    await renderLoaded();
    expect(cell("pe", "rank")).toHaveTextContent("—");
    expect(cell("pe", "median")).toHaveTextContent("—");
  });

  it("marks a caveat cell with † and lists the caveats per company", async () => {
    await renderLoaded();
    expect(cell("ev_ebitda", "peer:DE")).toHaveTextContent("(4.0x) †");
    expect(cell("pe", "peer:DE")).not.toHaveTextContent("†");
    expect(
      screen.getByText("† DE (EV / EBITDA): EBITDA includes financial services interest."),
    ).toBeVisible();
  });

  it("shows the target column in bold", async () => {
    await renderLoaded();
    expect(cell("pe", "target")).toHaveClass("font-semibold");
  });

  it("sends the basis toggle in the query", async () => {
    await renderLoaded();
    await userEvent.click(screen.getByRole("radio", { name: "Normalized" }));
    await waitFor(() =>
      expect(getComparison).toHaveBeenLastCalledWith({
        path: { ticker: "AAPL", set_id: 1 },
        query: { basis: "normalized" },
      }),
    );
  });

  it("shows an error when the comparison cannot load", async () => {
    getComparison.mockResolvedValue(errorResult(500) as never);
    renderView();
    expect(await screen.findByText("Could not load the comparison.")).toBeVisible();
  });
});

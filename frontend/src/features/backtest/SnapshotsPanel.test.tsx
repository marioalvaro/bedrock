// The Snapshots panel: the aggregate scores, the list and the sheet of one snapshot.
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getCompanyApiV1CompaniesTickerGet,
  getSnapshotApiV1CompaniesTickerSnapshotsSnapshotIdGet,
  listSnapshotsApiV1CompaniesTickerSnapshotsGet,
} from "@/api/generated/sdk.gen";
import { createQueryClient } from "@/lib/query-client";
import { setScale } from "@/lib/scale";
import { snapshotDetail, snapshotList, snapshotOut } from "@/test/accountability";
import { companyItem } from "@/test/companies";
import { errorResult, okResult } from "@/test/responses";

import { formatLocalTime } from "./backtestFormat";
import { SnapshotsPanel } from "./SnapshotsPanel";

vi.mock("@/api/generated/sdk.gen", () => ({
  getCompanyApiV1CompaniesTickerGet: vi.fn(),
  getSnapshotApiV1CompaniesTickerSnapshotsSnapshotIdGet: vi.fn(),
  listSnapshotsApiV1CompaniesTickerSnapshotsGet: vi.fn(),
}));

const list = vi.mocked(listSnapshotsApiV1CompaniesTickerSnapshotsGet);
const detail = vi.mocked(getSnapshotApiV1CompaniesTickerSnapshotsSnapshotIdGet);

beforeEach(() => {
  setScale("M");
  // The sheet compares the snapshot's classification mode with the company's (M7d S5).
  vi.mocked(getCompanyApiV1CompaniesTickerGet).mockResolvedValue(
    okResult(companyItem({ classification_mode: "off" })) as never,
  );
});
afterEach(() => vi.clearAllMocks());

function renderPanel(path = "/c/AAPL/backtest?view=snapshots") {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="c/:ticker/:tab" element={<SnapshotsPanel ticker="AAPL" />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const TAKEN = formatLocalTime("2026-11-09T15:30:00");
const rowsOf = (name: string) => within(screen.getByRole("table", { name })).getAllByRole("row");
const texts = (row: HTMLElement) =>
  within(row)
    .getAllByRole("cell")
    .map((cell) => cell.textContent);

async function renderLoaded() {
  list.mockResolvedValue(okResult(snapshotList()) as never);
  renderPanel();
  await screen.findByRole("table", { name: "Snapshots" });
}

async function openSheet() {
  detail.mockResolvedValue(okResult(snapshotDetail()) as never);
  await renderLoaded();
  await userEvent.click(rowsOf("Snapshots")[1]!);
  await screen.findByRole("table", { name: "Forecast against actual" });
}

const lineSelect = () => screen.getByRole("combobox", { name: "Line" }) as HTMLSelectElement;
const period = (label: string) =>
  within(screen.getByRole("table", { name: "Forecast against actual" })).getByRole("row", {
    name: new RegExp(`^${label}`),
  });

describe("states", () => {
  it("says it is loading", () => {
    list.mockReturnValue(new Promise(() => {}) as never);
    renderPanel();
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("says when it could not load", async () => {
    list.mockResolvedValue(errorResult(500) as never);
    renderPanel();
    expect(await screen.findByText("Could not load the snapshots.")).toBeInTheDocument();
  });

  it("points to the Scenarios tab when there are none", async () => {
    list.mockResolvedValue(okResult({ snapshots: [], summary: [] }) as never);
    renderPanel();
    expect(
      await screen.findByText("No snapshots yet. Take one from the Scenarios tab."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Snapshots" })).not.toBeInTheDocument();
  });
});

describe("the list", () => {
  it("has the columns of the spec", async () => {
    await renderLoaded();
    expect(
      within(rowsOf("Snapshots")[0]!)
        .getAllByRole("columnheader")
        .map((header) => header.textContent),
    ).toEqual(["Taken", "Scenario", "Note", "Data as of", "Scored periods", "Revenue MAPE"]);
  });

  it("shows a snapshot, and a dash for what it lacks", async () => {
    await renderLoaded();
    const [, first, second] = rowsOf("Snapshots");
    expect(texts(first!)).toEqual([TAKEN, "Main", "Before the print", "2025-10-31", "1", "3.1%"]);
    expect(texts(second!).slice(2)).toEqual(["—", "2025-10-31", "1", "—"]);
  });

  it("right-aligns only the numeric columns (.num)", async () => {
    await renderLoaded();
    expect(screen.getByRole("table", { name: "Snapshots" })).not.toHaveClass("num");
    const cells = within(rowsOf("Snapshots")[1]!).getAllByRole("cell");
    expect(cells.map((cell) => cell.classList.contains("num"))).toEqual([
      false,
      false,
      false,
      false,
      true,
      true,
    ]);
  });

  it("shows a dash for a manual company's data date", async () => {
    const base = snapshotList();
    base.snapshots = [{ ...base.snapshots[0]!, data_as_of: null }];
    list.mockResolvedValue(okResult(base) as never);
    renderPanel();
    await screen.findByRole("table", { name: "Snapshots" });
    expect(texts(rowsOf("Snapshots")[1]!)[3]).toBe("—");
  });
});

describe("the aggregate scores", () => {
  it("are by case, Base first, with the metric and stat controls", async () => {
    await renderLoaded();
    expect(screen.getByRole("combobox", { name: "Metric" })).toBeInTheDocument();
    expect(
      rowsOf("Scores")
        .slice(1)
        .map((row) => within(row).getByRole("rowheader").textContent),
    ).toEqual(["Base", "Bull", "Bear"]);
    expect(screen.getByRole("radio", { name: "Hit rate" })).toBeEnabled();
  });

  it("are not shown while nothing is scored, though the list is", async () => {
    list.mockResolvedValue(okResult(snapshotList({ summary: [] })) as never);
    renderPanel();
    await screen.findByRole("table", { name: "Snapshots" });
    expect(screen.queryByRole("combobox", { name: "Metric" })).not.toBeInTheDocument();
    expect(screen.getByText("Nothing scored yet: no actuals have landed.")).toBeInTheDocument();
  });
});

describe("the sheet", () => {
  it("opens from a row and asks for that snapshot", async () => {
    await openSheet();
    expect(detail).toHaveBeenCalledWith({ path: { ticker: "AAPL", snapshot_id: 7 } });
    expect(screen.getByRole("heading", { name: `Main · ${TAKEN}` })).toBeInTheDocument();
    expect(
      screen.getByText("Before the print", { selector: "[data-slot='sheet-description']" }),
    ).toBeInTheDocument();
  });

  it("opens from the keyboard too", async () => {
    detail.mockResolvedValue(okResult(snapshotDetail()) as never);
    await renderLoaded();
    within(rowsOf("Snapshots")[1]!).getByRole("button", { name: TAKEN }).focus();
    await userEvent.keyboard("{Enter}");
    expect(
      await screen.findByRole("table", { name: "Forecast against actual" }),
    ).toBeInTheDocument();
  });

  it("starts on Base and Revenue, against the actual, in the page scale", async () => {
    await openSheet();
    expect(screen.getByRole("radio", { name: "Base" })).toHaveAttribute("aria-checked", "true");
    expect(lineSelect().value).toBe("revenue");
    expect(texts(period("FY26"))).toEqual(["425,000", "416,161", "+2.1%", "Yes"]);
    expect(screen.getByText(/USD millions/)).toBeInTheDocument();
  });

  it("shows a dash where no actual has landed", async () => {
    await openSheet();
    expect(texts(period("FY27"))).toEqual(["450,000", "—", "—", "—"]);
  });

  it("says No for an actual out of range", async () => {
    const view = snapshotDetail();
    view.cases[0]!.lines[1]!.cells[0]!.in_range = false;
    detail.mockResolvedValue(okResult(view) as never);
    await renderLoaded();
    await userEvent.click(rowsOf("Snapshots")[1]!);
    await screen.findByRole("table", { name: "Forecast against actual" });
    expect(texts(period("FY26"))[3]).toBe("No");
  });

  it("prints a per-share line unscaled", async () => {
    const view = snapshotDetail();
    view.cases[0]!.lines = [
      {
        code: "eps_diluted",
        label: "Diluted EPS",
        unit: "USD/shares",
        cells: [{ ...view.cases[0]!.lines[1]!.cells[0]!, forecast: "7.5", actual: "7.46" }],
      },
    ];
    detail.mockResolvedValue(okResult(view) as never);
    await renderLoaded();
    await userEvent.click(rowsOf("Snapshots")[1]!);
    await screen.findByRole("table", { name: "Forecast against actual" });
    expect(lineSelect().value).toBe("eps_diluted");
    expect(texts(period("FY26")).slice(0, 2)).toEqual(["7.50", "7.46"]);
  });

  it("switches line", async () => {
    await openSheet();
    await userEvent.selectOptions(lineSelect(), "net_income");
    expect(texts(period("FY26")).slice(0, 2)).toEqual(["110,000", "—"]);
  });

  it("switches case and keeps the line where the case has it", async () => {
    await openSheet();
    await userEvent.click(screen.getByRole("radio", { name: "Bull" }));
    expect(lineSelect().value).toBe("revenue");
    expect(texts(period("FY26"))).toEqual(["470,000", "416,161", "+2.1%", "—"]);
  });

  it("falls back to the case's first line when it lacks the picked one", async () => {
    await openSheet();
    await userEvent.selectOptions(lineSelect(), "net_income");
    await userEvent.click(screen.getByRole("radio", { name: "Bull" }));
    expect(lineSelect().value).toBe("revenue");
  });

  it("lists the case's warnings", async () => {
    await openSheet();
    expect(screen.queryByText("Tax rate held flat")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: "Bull" }));
    expect(screen.getByText("Tax rate held flat")).toBeInTheDocument();
  });

  it("shows why a case could not run, in place of its table", async () => {
    await openSheet();
    await userEvent.click(screen.getByRole("radio", { name: "Bear" }));
    expect(screen.getByText("Set these drivers: gross_margin")).toBeInTheDocument();
    expect(
      screen.queryByRole("table", { name: "Forecast against actual" }),
    ).not.toBeInTheDocument();
  });

  it("lists the valuations, or a method's error", async () => {
    await openSheet();
    const rows = within(screen.getByRole("table", { name: "Valuations" })).getAllByRole("row");
    expect(within(rows[1]!).getByRole("rowheader")).toHaveTextContent("DCF");
    expect(texts(rows[1]!)).toEqual(["185.50", "-25.0%"]);
    expect(within(rows[2]!).getByRole("rowheader")).toHaveTextContent("EV/EBITDA");
    expect(texts(rows[2]!)).toEqual(["No peer multiple"]);
  });

  it("says when the snapshot could not load", async () => {
    detail.mockResolvedValue(errorResult(404) as never);
    await renderLoaded();
    await userEvent.click(rowsOf("Snapshots")[1]!);
    expect(await screen.findByText("Could not load the snapshot.")).toBeInTheDocument();
  });

  it("closes", async () => {
    await openSheet();
    await userEvent.keyboard("{Escape}");
    expect(
      screen.queryByRole("table", { name: "Forecast against actual" }),
    ).not.toBeInTheDocument();
  });
});

describe("the Auto badge (M7c, FR-ACC-05)", () => {
  it("marks a snapshot taken before a new filing was loaded", async () => {
    list.mockResolvedValue(
      okResult(
        snapshotList({ snapshots: [snapshotOut({ id: 8, origin: "auto" }), snapshotOut()] }),
      ) as never,
    );
    renderPanel();
    await screen.findByRole("table", { name: "Snapshots" });

    const [, auto, manual] = rowsOf("Snapshots");
    expect(within(auto!).getByText("Auto")).toHaveAttribute(
      "title",
      "Taken before a new filing was loaded",
    );
    expect(within(manual!).queryByText("Auto")).not.toBeInTheDocument();
  });
});

describe("the snapshot's classification mode (M7d S5)", () => {
  async function openWith(mode: "off" | "accepted" | "all" | null) {
    detail.mockResolvedValue(okResult(snapshotDetail()) as never);
    list.mockResolvedValue(
      okResult(snapshotList({ snapshots: [snapshotOut({ classification_mode: mode })] })) as never,
    );
    renderPanel();
    await screen.findByRole("table", { name: "Snapshots" });
    await userEvent.click(rowsOf("Snapshots")[1]!);
    await screen.findByRole("table", { name: "Forecast against actual" });
  }

  it("shows the mode the snapshot was taken under", async () => {
    await openWith("off");
    expect(await screen.findByText("Line classification: Off")).toBeInTheDocument();
    expect(screen.queryByText(/differs from the current setting/)).not.toBeInTheDocument();
  });

  it("says so when the company's mode has changed since", async () => {
    await openWith("accepted");
    expect(
      await screen.findByText(
        "Line classification: Accepted only · differs from the current setting",
      ),
    ).toBeInTheDocument();
  });

  it("says the mode was not recorded on a snapshot older than M7d", async () => {
    await openWith(null);
    expect(await screen.findByText("Line classification: not recorded")).toBeInTheDocument();
    expect(screen.queryByText(/differs from the current setting/)).not.toBeInTheDocument();
  });
});

// The Audit log panel: every logged change, its filter, paging and the rationale saved in place.
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  listAuditApiV1CompaniesTickerAuditGet,
  setAuditRationaleApiV1CompaniesTickerAuditRowIdPatch,
} from "@/api/generated/sdk.gen";
import { createQueryClient } from "@/lib/query-client";
import { auditPage, auditRow } from "@/test/accountability";
import { errorResult, okResult } from "@/test/responses";

import { AuditPanel } from "./AuditPanel";
import { formatLocalTime } from "./backtestFormat";

vi.mock("@/api/generated/sdk.gen", () => ({
  listAuditApiV1CompaniesTickerAuditGet: vi.fn(),
  setAuditRationaleApiV1CompaniesTickerAuditRowIdPatch: vi.fn(),
}));

const list = vi.mocked(listAuditApiV1CompaniesTickerAuditGet);
const patch = vi.mocked(setAuditRationaleApiV1CompaniesTickerAuditRowIdPatch);

afterEach(() => vi.clearAllMocks());

function renderPanel() {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AuditPanel ticker="AAPL" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function renderLoaded(page = auditPage()) {
  list.mockResolvedValue(okResult(page) as never);
  renderPanel();
  await screen.findByRole("table", { name: "Audit log" });
}

const rows = () => within(screen.getByRole("table", { name: "Audit log" })).getAllByRole("row");
const texts = (row: HTMLElement) =>
  within(row)
    .getAllByRole("cell")
    .slice(0, 5)
    .map((cell) => cell.textContent);
const rationale = (label = "Revenue growth FY27") =>
  screen.getByRole("textbox", { name: `Rationale for ${label}` }) as HTMLInputElement;
const filter = () => screen.getByRole("combobox", { name: "Change type" });

describe("states", () => {
  it("says it is loading", () => {
    list.mockReturnValue(new Promise(() => {}) as never);
    renderPanel();
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("says when it could not load, and keeps the filter", async () => {
    list.mockResolvedValue(errorResult(500) as never);
    renderPanel();
    expect(await screen.findByText("Could not load the audit log.")).toBeInTheDocument();
    expect(filter()).toBeInTheDocument();
  });

  it("says when nothing changed", async () => {
    list.mockResolvedValue(okResult(auditPage({ rows: [] })) as never);
    renderPanel();
    expect(await screen.findByText("No changes yet.")).toBeInTheDocument();
  });
});

describe("the table", () => {
  it("has the columns of the spec", async () => {
    await renderLoaded();
    expect(
      within(rows()[0]!)
        .getAllByRole("columnheader")
        .map((header) => header.textContent),
    ).toEqual(["When", "Change", "Where", "From", "To", "Rationale"]);
  });

  it("prints a change in its unit and in local time", async () => {
    await renderLoaded();
    expect(texts(rows()[1]!)).toEqual([
      formatLocalTime("2026-11-10T12:30:00"),
      "Revenue growth FY27",
      "Main · Base",
      "5.0%",
      "7.25%",
    ]);
  });

  it("keeps its text columns left-aligned (no .num)", async () => {
    await renderLoaded();
    expect(screen.getByRole("table", { name: "Audit log" })).not.toHaveClass("num");
  });

  it("shows a dash for an absent scope and value", async () => {
    await renderLoaded(
      auditPage({ rows: [auditRow({ scope: null, old_value: null, unit: null, new_value: "x" })] }),
    );
    expect(texts(rows()[1]!).slice(2)).toEqual(["—", "—", "x"]);
  });
});

describe("the filter", () => {
  it("lists the change types", async () => {
    await renderLoaded();
    expect(
      within(filter())
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual([
      "All",
      "Drivers",
      "Engines",
      "Year modes",
      "Valuation inputs",
      "Scenarios",
      "Adjustments",
    ]);
    expect(list).toHaveBeenLastCalledWith({ path: { ticker: "AAPL" }, query: {} });
  });

  it("asks for the chosen type", async () => {
    await renderLoaded();
    await userEvent.selectOptions(filter(), "Engines");
    await waitFor(() =>
      expect(list).toHaveBeenLastCalledWith({
        path: { ticker: "AAPL" },
        query: { entity: "engine_choice" },
      }),
    );
  });
});

describe("paging", () => {
  it("has no Load more on the last page", async () => {
    await renderLoaded();
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
  });

  it("appends the next page and stops at the last", async () => {
    list
      .mockResolvedValueOnce(okResult(auditPage({ next_before_id: 41 })) as never)
      .mockResolvedValueOnce(
        okResult(auditPage({ rows: [auditRow({ id: 40, label: "Gross margin FY27" })] })) as never,
      );
    renderPanel();
    await userEvent.click(await screen.findByRole("button", { name: "Load more" }));
    expect(await screen.findByText("Gross margin FY27")).toBeInTheDocument();
    expect(rows()).toHaveLength(3);
    expect(list).toHaveBeenLastCalledWith({ path: { ticker: "AAPL" }, query: { before_id: 41 } });
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
  });

  it("says when a further page failed, and keeps what it has", async () => {
    list
      .mockResolvedValueOnce(okResult(auditPage({ next_before_id: 41 })) as never)
      .mockResolvedValueOnce(errorResult(500) as never);
    renderPanel();
    await userEvent.click(await screen.findByRole("button", { name: "Load more" }));
    expect(await screen.findByText("Could not load more.")).toBeInTheDocument();
    expect(rows()).toHaveLength(2);
  });
});

describe("the rationale", () => {
  const saved = (text: string | null) => okResult(auditRow({ rationale: text })) as never;

  it("starts from the row's rationale", async () => {
    await renderLoaded(auditPage({ rows: [auditRow({ rationale: "Guide raised" })] }));
    expect(rationale().value).toBe("Guide raised");
  });

  it("saves on blur, trimmed", async () => {
    patch.mockResolvedValue(saved("Guide raised"));
    await renderLoaded();
    await userEvent.type(rationale(), "  Guide raised ");
    await userEvent.tab();
    expect(patch).toHaveBeenCalledTimes(1);
    expect(patch).toHaveBeenCalledWith({
      path: { ticker: "AAPL", row_id: 41 },
      body: { rationale: "Guide raised" },
    });
  });

  it("saves once on Enter", async () => {
    patch.mockResolvedValue(saved("Guide raised"));
    await renderLoaded();
    await userEvent.type(rationale(), "Guide raised{Enter}");
    await waitFor(() => expect(patch).toHaveBeenCalledTimes(1));
    await userEvent.tab();
    expect(patch).toHaveBeenCalledTimes(1);
  });

  it("does not save an unchanged rationale", async () => {
    await renderLoaded(auditPage({ rows: [auditRow({ rationale: "Guide raised" })] }));
    await userEvent.click(rationale());
    await userEvent.tab();
    expect(patch).not.toHaveBeenCalled();
  });

  it("clears a rationale with null", async () => {
    patch.mockResolvedValue(saved(null));
    await renderLoaded(auditPage({ rows: [auditRow({ rationale: "Guide raised" })] }));
    await userEvent.clear(rationale());
    await userEvent.tab();
    expect(patch).toHaveBeenCalledWith({
      path: { ticker: "AAPL", row_id: 41 },
      body: { rationale: null },
    });
  });

  it("takes at most 500 characters", async () => {
    await renderLoaded();
    expect(rationale()).toHaveAttribute("maxlength", "500");
  });

  it("shows the reloaded value after a save", async () => {
    patch.mockResolvedValue(saved("Guide raised"));
    await renderLoaded();
    list.mockResolvedValue(
      okResult(auditPage({ rows: [auditRow({ rationale: "Guide raised" })] })) as never,
    );
    const calls = list.mock.calls.length;
    await userEvent.type(rationale(), "Guide raised{Enter}");
    await waitFor(() => expect(list.mock.calls.length).toBeGreaterThan(calls));
    await waitFor(() => expect(rationale().value).toBe("Guide raised"));
  });

  it("shows the API's detail and keeps the text when it fails", async () => {
    patch.mockResolvedValue(errorResult(422, { detail: "At most 500 characters" }) as never);
    await renderLoaded();
    await userEvent.type(rationale(), "Too long{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("At most 500 characters");
    expect(rationale().value).toBe("Too long");
  });

  it("falls back to a plain text on an error without a detail", async () => {
    patch.mockResolvedValue(errorResult(500, {}) as never);
    await renderLoaded();
    await userEvent.type(rationale(), "Text{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not save the rationale.");
  });

  it("clears the error once a later save works", async () => {
    patch.mockResolvedValueOnce(errorResult(500, {}) as never).mockResolvedValueOnce(saved("Text"));
    await renderLoaded();
    await userEvent.type(rationale(), "Text{Enter}");
    await screen.findByRole("alert");
    await userEvent.click(rationale());
    await userEvent.tab();
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(patch).toHaveBeenCalledTimes(2);
  });
});

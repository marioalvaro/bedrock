import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Td, Th } from "./table";

function renderRow(head: React.ReactNode, cell: React.ReactNode) {
  render(
    <table>
      <thead>
        <tr>{head}</tr>
      </thead>
      <tbody>
        <tr>{cell}</tr>
      </tbody>
    </table>,
  );
}

describe("table cells", () => {
  it("draws a muted, left-aligned header and a plain cell on one line", () => {
    renderRow(<Th>Line</Th>, <Td>Revenue</Td>);
    const head = screen.getByRole("columnheader", { name: "Line" });
    expect(head.className.split(" ").sort()).toEqual(
      [
        "font-normal",
        "px-2",
        "py-1",
        "text-left",
        "text-muted-foreground",
        "whitespace-nowrap",
      ].sort(),
    );
    expect(screen.getByRole("cell", { name: "Revenue" }).className.split(" ").sort()).toEqual(
      ["px-2", "py-1", "whitespace-nowrap"].sort(),
    );
  });

  it("right-aligns a numeric column in tabular figures", () => {
    renderRow(<Th numeric>Actual</Th>, <Td numeric>416.2B</Td>);
    expect(screen.getByRole("columnheader", { name: "Actual" })).toHaveClass("text-right");
    expect(screen.getByRole("columnheader", { name: "Actual" })).not.toHaveClass("text-left");
    expect(screen.getByRole("cell", { name: "416.2B" })).toHaveClass("num", "text-right");
  });

  it("lets a caller's class win over a default and passes other props through", () => {
    renderRow(
      <Th scope="col" className="font-medium">
        AAPL
      </Th>,
      <Td className="align-top whitespace-normal">wraps</Td>,
    );
    const head = screen.getByRole("columnheader", { name: "AAPL" });
    expect(head).toHaveClass("font-medium");
    expect(head).not.toHaveClass("font-normal");
    expect(head).toHaveAttribute("scope", "col");
    const cell = screen.getByRole("cell", { name: "wraps" });
    expect(cell).toHaveClass("align-top", "whitespace-normal");
    expect(cell).not.toHaveClass("whitespace-nowrap");
  });
});

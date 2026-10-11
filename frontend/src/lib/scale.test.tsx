import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { getScale, setScale, useScale } from "./scale";

function ScaleLabel({ id }: { id: string }) {
  const scale = useScale();
  return <span data-testid={id}>{scale}</span>;
}

afterEach(() => {
  act(() => setScale("M"));
  localStorage.clear();
});

describe("scale store", () => {
  it("defaults to M", () => {
    expect(getScale()).toBe("M");
  });

  it("keeps two consumers in sync", () => {
    render(
      <>
        <ScaleLabel id="a" />
        <ScaleLabel id="b" />
      </>,
    );

    act(() => setScale("B"));

    expect(screen.getByTestId("a")).toHaveTextContent("B");
    expect(screen.getByTestId("b")).toHaveTextContent("B");
  });

  it("persists the choice in localStorage", () => {
    act(() => setScale("K"));

    expect(localStorage.getItem("scale")).toBe("K");
  });
});

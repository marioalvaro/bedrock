import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { act } from "react";
import { beforeEach, describe, expect, it } from "vitest";

import { setTheme } from "@/lib/theme";

import { ThemeToggle } from "./ThemeToggle";

function icon(button: HTMLElement): "sun" | "moon" | null {
  if (button.querySelector(".lucide-sun")) return "sun";
  if (button.querySelector(".lucide-moon")) return "moon";
  return null;
}

describe("ThemeToggle", () => {
  beforeEach(() => {
    localStorage.clear();
    act(() => setTheme("light"));
  });

  it("switches to dark and shows the sun icon", async () => {
    render(<ThemeToggle />);
    const button = screen.getByRole("button", { name: "Toggle theme" });
    expect(icon(button)).toBe("moon");

    await userEvent.click(button);

    expect(icon(button)).toBe("sun");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("keeps every toggle on the page in sync", async () => {
    render(
      <>
        <ThemeToggle />
        <ThemeToggle />
      </>,
    );
    const [first, second] = screen.getAllByRole("button", { name: "Toggle theme" });

    await userEvent.click(first);

    expect(icon(first)).toBe("sun");
    expect(icon(second)).toBe("sun");
  });
});

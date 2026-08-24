import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { fmtPct, fmtUsd, ModeBadge } from "./ui";

describe("fmtUsd", () => {
  it("formats a positive number with two decimals", () => {
    expect(fmtUsd(1234.5)).toBe("$1,234.50");
  });

  it("renders a dash for null/undefined instead of $NaN", () => {
    expect(fmtUsd(null)).toBe("—");
    expect(fmtUsd(undefined)).toBe("—");
  });
});

describe("fmtPct", () => {
  it("prefixes positive values with a plus sign", () => {
    expect(fmtPct(4.2)).toBe("+4.20%");
  });

  it("does not double the minus sign for negative values", () => {
    expect(fmtPct(-4.2)).toBe("-4.20%");
  });
});

describe("ModeBadge", () => {
  it("renders the LIVE badge distinctly so it can never be confused with PAPER/TESTNET", () => {
    render(<ModeBadge mode="LIVE" />);
    const badge = screen.getByText("LIVE");
    expect(badge).toBeInTheDocument();
    expect(badge.className).toMatch(/bg-red-600/);
  });

  it("renders PAPER and TESTNET with different colors from each other", () => {
    const { unmount } = render(<ModeBadge mode="PAPER" />);
    const paperClass = screen.getByText("PAPER").className;
    unmount();
    render(<ModeBadge mode="TESTNET" />);
    const testnetClass = screen.getByText("TESTNET").className;
    expect(paperClass).not.toBe(testnetClass);
  });
});

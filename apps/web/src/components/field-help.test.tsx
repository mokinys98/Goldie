import React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { FieldHelp } from "./field-help";

describe("FieldHelp", () => {
  afterEach(() => cleanup());

  it("exposes the complete explanation to keyboard and assistive technology", () => {
    render(
      <FieldHelp
        label="Risk per trade"
        metadata={{
          description: "Capital allowed to be risked by one trade.",
          unit: "percent",
          minimum: 0.01,
          maximum: 5,
          default: 0.25,
          impact: "Increasing it raises position size and loss risk.",
        }}
      />,
    );
    const help = screen.getByRole("button", { name: /Risk per trade/ });
    expect(help).toHaveAttribute("data-tooltip", expect.stringContaining("Unit: percent"));
    expect(help).toHaveAttribute("aria-label", expect.stringContaining("Allowed range"));
    expect(help).toHaveAttribute("aria-label", expect.stringContaining("Increasing it"));
  });
});

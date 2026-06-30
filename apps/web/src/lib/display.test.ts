import { describe, expect, it } from "vitest";
import {
  displayJson,
  displayValue,
  exclusiveZeroInputValue,
  exclusiveZeroStoredValue,
} from "./display";

describe("exclusive-zero display", () => {
  it("shows the internal exclusive minimum as zero", () => {
    expect(displayValue(1e-9)).toBe("0");
    expect(displayValue("1e-9")).toBe("0");
    expect(exclusiveZeroInputValue(1e-9)).toBe(0);
  });

  it("keeps regular small values unchanged", () => {
    expect(displayValue(0.00001)).toBe("0.00001");
  });

  it("stores a displayed zero above an exclusive zero bound", () => {
    expect(exclusiveZeroStoredValue(0, 0)).toBe(1e-9);
    expect(exclusiveZeroStoredValue(0, undefined)).toBe(0);
  });

  it("replaces exclusive zero values in displayed JSON only", () => {
    expect(displayJson({ minimum: 1e-9, regular: 2 })).toContain('"minimum": 0');
  });
});

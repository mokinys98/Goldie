const EXCLUSIVE_ZERO = 1e-9;

export function displayValue(value: unknown): string {
  if (isExclusiveZero(value)) return "0";
  return String(value);
}

export function displayJson(value: unknown): string {
  return JSON.stringify(
    value,
    (_key, item) => isExclusiveZero(item) ? 0 : item,
    2,
  );
}

export function isExclusiveZero(value: unknown): boolean {
  return (typeof value === "number" || typeof value === "string")
    && Number(value) === EXCLUSIVE_ZERO;
}

export function exclusiveZeroInputValue(value: number): number {
  return isExclusiveZero(value) ? 0 : value;
}

export function exclusiveZeroStoredValue(
  displayedValue: number,
  exclusiveMinimum: number | undefined,
): number {
  return displayedValue === 0 && exclusiveMinimum === 0
    ? EXCLUSIVE_ZERO
    : displayedValue;
}

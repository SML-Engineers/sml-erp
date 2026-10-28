import { formatDecimal, sumDecimal } from "./decimal";

test("adds money exactly, without floating-point errors", () => {
  expect(0.1 + 0.2).not.toBe(0.3); // why this exists
  expect(sumDecimal(["0.10", "0.20"])).toBe("0.30");
  expect(sumDecimal(["13102.08", "97767.00", "230150.00"])).toBe("341019.08");
});

test("handles negatives, blanks and whole numbers", () => {
  expect(sumDecimal(["100", "-25.50", "", null, undefined])).toBe("74.50");
  expect(sumDecimal([])).toBe("0.00");
  expect(sumDecimal(["-0.05", "0.01"])).toBe("-0.04");
});

test("refuses values that would lose precision or are not numbers", () => {
  expect(() => sumDecimal(["1.005"])).toThrow();
  expect(() => sumDecimal(["12,000.00"])).toThrow();
  expect(sumDecimal(["1.500"])).toBe("1.50"); // trailing zeros are fine
});

test("formats with thousands separators", () => {
  expect(formatDecimal("230150.00")).toBe("230,150.00");
  expect(formatDecimal("-1234567.5")).toBe("-1,234,567.5");
  expect(formatDecimal("999")).toBe("999");
});

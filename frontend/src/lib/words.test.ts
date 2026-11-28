import { codeAndName } from "./words";

// Testing T2 (20 Nov 2026): "EN8 EN8 steel bar" when the name starts with the code.
test("the code is not repeated when the name starts with it", () => {
  expect(codeAndName("EN8", "EN8 steel bar")).toBe("EN8 steel bar");
  expect(codeAndName("PP-H", "Polypropylene")).toBe("PP-H Polypropylene");
});

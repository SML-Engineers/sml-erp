import type { TaxCode } from "../api/taxes";
import { offeredTaxCodes } from "./taxCodes";

const code = (c: string, use: TaxCode["use"], extra: Partial<TaxCode> = {}): TaxCode => ({
  id: 1,
  code: c,
  name: c,
  description: "",
  use,
  is_active: true,
  in_use: false,
  has_rate_today: true,
  components: [],
  ...extra,
});

// Testing T1 (21 Nov 2026): a code with a tax that has no rate today is not offered.
test("forms offer only active codes for their side with a rate today, and keep a code in use", () => {
  const codes = [
    code("VAT", "both"),
    code("VAT-SSCL-M", "sales", { has_rate_today: false }),
    code("WHT", "purchases"),
    code("OLD", "both", { is_active: false }),
  ];
  expect(offeredTaxCodes(codes, "sales").map((c) => c.code)).toEqual(["VAT"]);
  expect(offeredTaxCodes(codes, "purchases").map((c) => c.code)).toEqual(["VAT", "WHT"]);
  expect(offeredTaxCodes(codes, "sales", ["VAT-SSCL-M", null]).map((c) => c.code)).toEqual(["VAT", "VAT-SSCL-M"]);
  expect(offeredTaxCodes(undefined, "sales")).toEqual([]);
});

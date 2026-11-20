import { dayMonthYear, invoiceDateAge, monthsBack } from "./invoiceDates";

test("months back keep the day, or take the month's last day", () => {
  expect(monthsBack("2026-11-20", 2)).toBe("2026-09-20");
  expect(monthsBack("2026-12-31", 2)).toBe("2026-10-31");
  expect(monthsBack("2027-04-30", 2)).toBe("2027-02-28");
  expect(monthsBack("2027-01-15", 12)).toBe("2026-01-15");
  expect(monthsBack("2028-02-29", 12)).toBe("2027-02-28");
});

test("an invoice date is ok, old (more than 2 months) or too old (more than a year)", () => {
  const today = "2026-11-20";
  expect(invoiceDateAge(null, today)).toBe("ok");
  expect(invoiceDateAge("2026-09-20", today)).toBe("ok");
  expect(invoiceDateAge("2026-09-19", today)).toBe("old");
  expect(invoiceDateAge("2025-11-20", today)).toBe("old");
  expect(invoiceDateAge("2025-11-19", today)).toBe("too_old");
  expect(invoiceDateAge("2006-11-13", today)).toBe("too_old");
  expect(dayMonthYear("2026-08-13")).toBe("13/08/2026");
});

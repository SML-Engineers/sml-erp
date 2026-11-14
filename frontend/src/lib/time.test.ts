import { factoryToday, formatDate, formatDateTime, formatTime, normaliseTime } from "./time";

test("moments show in Sri Lanka time on the 24-hour clock, whatever the PC's time zone", () => {
  // 15:30 UTC is 21:00 in Sri Lanka (UTC+05:30); 18:31 UTC crosses midnight there.
  expect(formatDateTime("2026-11-12T15:30:00Z")).toBe("2026-11-12 21:00");
  expect(formatDateTime("2026-11-12T18:31:00Z")).toBe("2026-11-13 00:01");
  expect(formatDate("2026-11-12T18:31:00Z")).toBe("2026-11-13");
  expect(formatTime("2026-11-12T08:15:00+05:30")).toBe("08:15");
  expect(formatDateTime(null)).toBe("");
  expect(formatDateTime("not a date")).toBe("");
});

test("today is the factory's date", () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-11-12T19:00:00Z")); // 00:30 on the 13th in Sri Lanka
  expect(factoryToday()).toBe("2026-11-13");
  vi.useRealTimers();
});

test("a typed time is tidied into HH:MM", () => {
  expect(normaliseTime("830")).toBe("08:30");
  expect(normaliseTime("1730")).toBe("17:30");
  expect(normaliseTime("8:5")).toBe("08:05");
  expect(normaliseTime("08.30")).toBe("08:30");
  expect(normaliseTime("25:00")).toBe("25:00");
  expect(normaliseTime("")).toBe("");
});

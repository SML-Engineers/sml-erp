import { fireEvent, screen, waitFor } from "@testing-library/react";

import type { Checklist, YearClose } from "../api/close";
import { mockApi, renderAt } from "../test-utils";
import ClosePage from "./ClosePage";

function lastMonth(): string {
  const now = new Date();
  const d = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

const item = (key: string, label: string, done: boolean) => ({
  key,
  label,
  done,
  detail: done ? "Posted." : "Not done.",
  ticked_by: null,
  ticked_at: null,
  note: "",
});

const checklist: Checklist = {
  month: lastMonth(),
  is_closed: false,
  can_tick: true,
  can_close: false,
  ready: false,
  items: [item("depreciation", "Depreciation posted", true), item("accruals", "Accruals and prepayments entered", false)],
};
const year: YearClose = { year: 2025, label: "2025-26", open_months: [], closed: false, can_close: false, history: [] };

test("the Accountant ticks the accruals with a note", async () => {
  const calls = mockApi({
    [`GET /api/v1/month-end/${lastMonth()}/`]: { body: checklist },
    [`POST /api/v1/month-end/${lastMonth()}/tick/`]: { status: 201, body: { ...checklist, ready: true } },
    "GET /api/v1/year-end/": { body: year },
  });
  renderAt("/month-end", <ClosePage />);
  const note = await screen.findByLabelText("Note for Accruals and prepayments entered");
  fireEvent.change(note, { target: { value: "Electricity accrued" } });
  fireEvent.click(screen.getByRole("button", { name: "Mark done" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      `/api/v1/month-end/${lastMonth()}/tick/`,
      expect.objectContaining({ method: "POST", body: JSON.stringify({ item: "accruals", note: "Electricity accrued" }) }),
    ),
  );
  expect(await screen.findByText(/2025-26/)).toBeInTheDocument();
});

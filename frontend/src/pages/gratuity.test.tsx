import { fireEvent, screen, waitFor } from "@testing-library/react";

import type { GratuityList } from "../api/gratuity";
import { mockApi, renderAt } from "../test-utils";
import GratuityPage from "./GratuityPage";

const row = {
  id: 3,
  number: "E003",
  name: "Sunil Silva",
  division: "WS",
  join_date: "2020-01-15",
  service_from: "2020-01-15",
  months_per_year: "0.50",
  after_years: 5,
  by_act: true,
  years: 6,
  wage: "66000.00",
  liability: "198000.00",
  provided: "198000.00",
  waiting: null,
};
const list: GratuityList = { results: [row], can_enter: true };

test("the Accountant sends better terms to the Director", async () => {
  const waiting = {
    id: 9,
    effective_from: "2026-11",
    service_from: "2019-06-01",
    months_per_year: "1.00",
    after_years: 3,
    reason: "Agreed",
    status: "awaiting",
    status_label: "Waiting for the Director",
    created_by: "Accountant",
    can_approve: false,
    can_withdraw: true,
  };
  const calls = mockApi({
    "GET /api/v1/gratuity/": { body: list },
    "POST /api/v1/gratuity/": { body: { ...list, results: [{ ...row, waiting }] } },
  });
  renderAt("/gratuity", <GratuityPage />);
  expect(await screen.findByText("Liability if everyone left today: LKR 198,000.00")).toBeInTheDocument();
  expect(screen.getByText("The Act")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Change" }));
  fireEvent.change(screen.getByLabelText("From pay month"), { target: { value: "2026-11" } });
  fireEvent.change(screen.getByLabelText("Months' pay per completed year"), { target: { value: "1" } });
  fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Agreed" } });
  fireEvent.click(screen.getByRole("button", { name: "Send to the Director" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/gratuity/",
      expect.objectContaining({
        body: JSON.stringify({
          employee_id: 3,
          effective_from: "2026-11",
          service_from: "2020-01-15",
          months_per_year: "1",
          after_years: "5",
          reason: "Agreed",
        }),
      }),
    ),
  );
  expect(await screen.findByText(/Waiting for the Director: from 2026-11, 1.00 month/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Withdraw" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
});

test("the Director approves", async () => {
  const waiting = {
    id: 9,
    effective_from: "2026-11",
    service_from: "2019-06-01",
    months_per_year: "1.00",
    after_years: 3,
    reason: "Agreed",
    status: "awaiting",
    status_label: "Waiting for the Director",
    created_by: "Accountant",
    can_approve: true,
    can_withdraw: false,
  };
  const calls = mockApi({
    "GET /api/v1/gratuity/": { body: { results: [{ ...row, waiting }], can_enter: false } },
    "POST /api/v1/gratuity/settings/9/approve/": {
      body: { results: [{ ...row, by_act: false, months_per_year: "1.00", after_years: 3 }], can_enter: false },
    },
  });
  renderAt("/gratuity", <GratuityPage />);
  fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
  expect(await screen.findByText("1.00 month(s) a year after 3 years")).toBeInTheDocument();
  expect(calls).toHaveBeenCalledWith("/api/v1/gratuity/settings/9/approve/", expect.objectContaining({ method: "POST" }));
  expect(screen.queryByRole("button", { name: "Change" })).not.toBeInTheDocument();
});

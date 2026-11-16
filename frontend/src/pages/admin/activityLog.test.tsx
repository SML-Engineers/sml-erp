import { fireEvent, screen, waitFor } from "@testing-library/react";

import { mockApi, renderAt } from "../../test-utils";
import ActivityLogPage from "./ActivityLogPage";

const row = {
  id: 2,
  occurred_at: "2026-11-16T04:30:00Z",
  user_email: "director@demo.sml.lk",
  ip_address: "10.0.0.5",
  kind: "download",
  category: "payslip",
  path: "/api/v1/my/payslips/3/",
  file_name: "payslip-2026-10.pdf",
  level: "sensitive",
};

// Owner, 14 Nov 2026: who opened payslips, salaries and bank details, and every download.
test("views and downloads are listed and can be filtered", async () => {
  const calls = mockApi({
    "GET /api/v1/activity-log/": { body: [row] },
    "GET /api/v1/activity-log/?person=director%40demo.sml.lk&kind=download": { body: [row] },
  });
  renderAt("/admin/activity", <ActivityLogPage />);
  const table = await screen.findByRole("table", { name: "Views and downloads" });
  expect(table).toHaveTextContent("director@demo.sml.lk");
  expect(table).toHaveTextContent("Downloaded");
  expect(table).toHaveTextContent("Payslips");
  expect(table).toHaveTextContent("payslip-2026-10.pdf");
  expect(table).toHaveTextContent("10:00"); // Sri Lanka time, 24-hour clock

  fireEvent.change(screen.getByLabelText("Person (email)"), { target: { value: "director@demo.sml.lk" } });
  fireEvent.change(screen.getByLabelText("Viewed or downloaded"), { target: { value: "download" } });
  fireEvent.click(screen.getByRole("button", { name: "Show" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith("/api/v1/activity-log/?person=director%40demo.sml.lk&kind=download", expect.anything()),
  );
});

test("an empty record says so", async () => {
  mockApi({ "GET /api/v1/activity-log/": { body: [] } });
  renderAt("/admin/activity", <ActivityLogPage />);
  expect(await screen.findByText("Nothing recorded for these filters.")).toBeInTheDocument();
});

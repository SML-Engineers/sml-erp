import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";

import type { Bell } from "../api/notifications";
import NotificationSettingsPage from "../pages/NotificationSettingsPage";
import { mockApi, renderAt } from "../test-utils";
import NotificationBell from "./NotificationBell";

const bell: Bell = {
  unread: 1,
  items: [
    {
      id: 5,
      event: "approval_waiting",
      title: "Voucher WS261029001 is waiting for your approval (level 2)",
      body: "",
      link: "/vouchers/1",
      created_at: "2026-10-29T08:00:00Z",
      read: false,
    },
  ],
};

function renderBell() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<NotificationBell />} />
          <Route path="/vouchers/1" element={<p>Voucher page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("the bell counts unread notifications and opens one, marking it read", async () => {
  const calls = mockApi({
    "GET /api/v1/notifications/": { body: bell },
    "POST /api/v1/notifications/read/": { body: { unread: 0 } },
  });
  renderBell();

  const button = await screen.findByRole("button", { name: "Notifications, 1 unread" });
  fireEvent.click(button);
  const panel = screen.getByRole("dialog", { name: "Notifications" });
  fireEvent.click(within(panel).getByRole("button", { name: /WS261029001 is waiting/ }));
  expect(await screen.findByText("Voucher page")).toBeInTheDocument();
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/notifications/read/",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ ids: [5] }) }),
    ),
  );
});

test("all notifications can be marked read at once", async () => {
  const calls = mockApi({
    "GET /api/v1/notifications/": { body: bell },
    "POST /api/v1/notifications/read/": { body: { unread: 0 } },
  });
  renderBell();

  fireEvent.click(await screen.findByRole("button", { name: "Notifications, 1 unread" }));
  fireEvent.click(screen.getByRole("button", { name: "Mark all as read" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/notifications/read/",
      expect.objectContaining({ method: "POST", body: JSON.stringify({}) }),
    ),
  );
});

test("a person switches off emails for one kind of event", async () => {
  const rows = [
    { event: "approval_waiting", label: "A document is waiting for my approval", in_app: true, email: true },
  ];
  const calls = mockApi({
    "GET /api/v1/notifications/preferences/": { body: rows },
    "PUT /api/v1/notifications/preferences/": { body: [{ ...rows[0], email: false }] },
  });
  renderAt("/account/notifications", <NotificationSettingsPage />);

  const email = await screen.findByLabelText("By email: A document is waiting for my approval");
  expect(email).toBeChecked();
  fireEvent.click(email);
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/notifications/preferences/",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({ event: "approval_waiting", email: false }),
      }),
    ),
  );
  await waitFor(() => expect(screen.getByLabelText("By email: A document is waiting for my approval")).not.toBeChecked());
});

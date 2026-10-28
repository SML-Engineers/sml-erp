import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";

import type { CurrentUser } from "../api/auth";
import { mockApi, sampleUser } from "../test-utils";
import AppLayout from "./AppLayout";
import { visibleMenu } from "./menu";

function renderLayout(user: CurrentUser) {
  const client = new QueryClient();
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route element={<AppLayout user={user} />}>
            <Route index element={<p>Dashboard content</p>} />
            <Route path="admin/users" element={<p>Users content</p>} />
          </Route>
          <Route path="/login" element={<p>Login page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const clerk: CurrentUser = {
  ...sampleUser,
  full_name: "Nimal Perera",
  access: { areas: { dashboard: ["view"], vouchers: ["enter", "view"] }, actions: [], divisions: ["IM"] },
};

const admin: CurrentUser = {
  ...sampleUser,
  full_name: "Admin",
  access: {
    areas: { users: ["enter", "manage", "view"], audit_logs: ["view"] },
    actions: [],
    divisions: "all",
  },
};

test("the menu shows only areas the user can view", () => {
  renderLayout(clerk);
  const menu = screen.getByRole("navigation", { name: "Main menu" });
  expect(within(menu).getByRole("link", { name: "Dashboard" })).toBeInTheDocument();
  expect(within(menu).queryByText("Administration")).not.toBeInTheDocument();
  expect(within(menu).queryByRole("link", { name: "Users" })).not.toBeInTheDocument();
  expect(within(menu).queryByRole("link", { name: "Audit log" })).not.toBeInTheDocument();
});

test("administrators see the administration pages", () => {
  renderLayout(admin);
  const menu = screen.getByRole("navigation", { name: "Main menu" });
  expect(within(menu).getByRole("link", { name: "Users" })).toBeInTheDocument();
  expect(within(menu).getByRole("link", { name: "Access review" })).toBeInTheDocument();
  expect(within(menu).getByRole("link", { name: "Audit log" })).toBeInTheDocument();
});

test("menu items lead to their pages", () => {
  renderLayout(admin);
  expect(screen.getByText("Dashboard content")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("link", { name: "Users" }));
  expect(screen.getByText("Users content")).toBeInTheDocument();
});

test("on a phone the menu button opens and closes the menu", () => {
  renderLayout(clerk);
  const toggle = screen.getByRole("button", { name: "Menu" });
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  fireEvent.click(toggle);
  expect(toggle).toHaveAttribute("aria-expanded", "true");
  fireEvent.click(screen.getByRole("button", { name: "Close menu" }));
  expect(toggle).toHaveAttribute("aria-expanded", "false");
});

test("the user menu signs out", async () => {
  mockApi({ "POST /api/v1/auth/logout/": { body: { status: "signed_out" } } });
  renderLayout(clerk);
  fireEvent.click(screen.getByRole("button", { name: /Nimal Perera/ }));
  expect(screen.getByRole("menuitem", { name: "Change password" })).toHaveAttribute(
    "href",
    "/account/password",
  );
  fireEvent.click(screen.getByRole("menuitem", { name: "Sign out" }));
  expect(await screen.findByText("Login page")).toBeInTheDocument();
});

test("empty menu sections are left out", () => {
  expect(visibleMenu(clerk.access).map((s) => s.label)).toEqual(["menu.main", "menu.vouchers"]);
});

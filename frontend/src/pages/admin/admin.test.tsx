import { fireEvent, screen, within } from "@testing-library/react";

import type { AccessGrid, UserRecord } from "../../api/admin";
import type { CurrentUser } from "../../api/auth";
import { mockApi, renderAt, sampleUser } from "../../test-utils";
import AccessReviewPage from "./AccessReviewPage";
import UserAccessPage from "./UserAccessPage";
import UsersPage from "./UsersPage";

const admin: CurrentUser = {
  ...sampleUser,
  email: "admin@sml.lk",
  full_name: "Admin",
  access: { areas: { users: ["enter", "manage", "view"] }, actions: [], divisions: "all" },
};

const director: CurrentUser = {
  ...sampleUser,
  access: { areas: { users: ["view"] }, actions: ["confirm_sensitive_grants"], divisions: "all" },
};

const clerk: UserRecord = {
  id: 7,
  email: "clerk@sml.lk",
  full_name: "Nimal Perera",
  is_active: true,
  two_factor_required: false,
  two_factor_enabled: false,
  must_change_password: false,
  all_divisions: false,
  divisions: ["IM"],
  roles: [
    { code: "clerk", name: "Accounts Clerk", assigned_at: "", reason: "", conflict_warning: "" },
  ],
  last_login: null,
  date_joined: "2026-10-01T00:00:00Z",
};

const grid: AccessGrid = {
  user: clerk,
  areas: [
    {
      area: "vouchers",
      label: "Payment vouchers",
      levels: [
        { level: "view", from_roles: true, override: null, effective: true },
        { level: "enter", from_roles: true, override: null, effective: true },
        { level: "approve", from_roles: false, override: null, effective: false },
        { level: "manage", from_roles: false, override: null, effective: false },
      ],
    },
  ],
  actions: [
    {
      action: "record_payment",
      label: "Record supplier payments",
      from_roles: false,
      override: null,
      effective: false,
    },
  ],
};

const accessPageApi = (extra = {}) => ({
  "GET /api/v1/users/7/access/": { body: grid },
  "GET /api/v1/users/7/overrides/": { body: [] },
  "GET /api/v1/users/": { body: [clerk] },
  "GET /api/v1/roles/": {
    body: [
      { id: 1, code: "clerk", name: "Accounts Clerk", description: "", is_standard: true, is_active: true },
      { id: 2, code: "cashier", name: "Cashier / Payment Officer", description: "", is_standard: true, is_active: true },
    ],
  },
  "GET /api/v1/divisions/": { body: [{ id: 2, code: "IM", name: "Plastic Injection Moulding" }] },
  "GET /api/v1/users/7/sections/": { body: { all_sections: true, sections: [] } },
  "GET /api/v1/sections/": { body: [{ id: 1, code: "IM-MLD", name: "Moulding", division: "IM" }] },
  ...extra,
});

test("users list shows people and gives a one-time temporary password", async () => {
  mockApi({
    "GET /api/v1/users/": { body: [clerk] },
    "POST /api/v1/users/": { status: 201, body: { ...clerk, id: 8, email: "new@sml.lk", temporary_password: "Tmp-9x2kLm" } },
  });
  renderAt("/admin/users", <UsersPage me={admin} />);

  expect(await screen.findByRole("link", { name: "Nimal Perera" })).toHaveAttribute("href", "/admin/users/7");
  fireEvent.change(screen.getByLabelText("Full name"), { target: { value: "New Person" } });
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "new@sml.lk" } });
  fireEvent.click(screen.getByRole("button", { name: "Create user" }));
  expect(await screen.findByText("Tmp-9x2kLm")).toBeInTheDocument();
  expect(screen.getByText(/stays switched off until you give it roles and divisions/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Set up Nimal Perera now" })).toHaveAttribute("href", "/admin/users/8");
});

test("users without manage access cannot add users", async () => {
  mockApi({ "GET /api/v1/users/": { body: [clerk] } });
  renderAt("/admin/users", <UsersPage me={director} />);
  await screen.findByText("Nimal Perera");
  expect(screen.queryByRole("button", { name: "Create user" })).not.toBeInTheDocument();
});

test("granting access from the grid sends the area, level and reason", async () => {
  const api = mockApi(
    accessPageApi({
      "POST /api/v1/users/7/overrides/": (sent: unknown) => ({
        status: 201,
        body: { id: 1, status: "pending", ...(sent as object) },
      }),
    }),
  );
  renderAt("/admin/users/7", <UserAccessPage me={admin} />, "/admin/users/:id");

  fireEvent.click(await screen.findByRole("button", { name: "Payment vouchers: Approve" }));
  fireEvent.change(screen.getByLabelText("Reason", { selector: ".override-form input" }), {
    target: { value: "Cover while the accountant is on leave" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Grant" }));

  expect(await screen.findByText(/takes effect once the Director confirms/)).toBeInTheDocument();
  const call = api.mock.calls.find(([url, init]) => url === "/api/v1/users/7/overrides/" && init?.method === "POST");
  expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({
    effect: "grant",
    area: "vouchers",
    level: "approve",
    reason: "Cover while the accountant is on leave",
  });
});

test("conflicting roles show the warnings and ask for a reason", async () => {
  mockApi(
    accessPageApi({
      "PUT /api/v1/users/7/roles/": {
        status: 400,
        body: {
          detail: "These roles should normally be held by different people. Give a reason to assign them anyway.",
          warnings: ["Accounts Clerk + Cashier / Payment Officer: one person records and pays the same vouchers."],
        },
      },
    }),
  );
  renderAt("/admin/users/7", <UserAccessPage me={admin} />, "/admin/users/:id");

  fireEvent.click(await screen.findByRole("checkbox", { name: "Cashier / Payment Officer" }));
  fireEvent.click(screen.getByRole("button", { name: "Save roles" }));

  const alert = await screen.findByRole("alert");
  expect(within(alert).getByText(/records and pays the same vouchers/)).toBeInTheDocument();
});

test("an administrator's own account is read-only", async () => {
  mockApi(accessPageApi({ "GET /api/v1/users/7/access/": { body: { ...grid, user: { ...clerk, email: "admin@sml.lk" } } } }));
  renderAt("/admin/users/7", <UserAccessPage me={admin} />, "/admin/users/:id");
  expect(await screen.findByText(/Another administrator must change your access/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Save roles" })).not.toBeInTheDocument();
});

test("only the Director can record the access review", async () => {
  const review = {
    period: "2026-Q4",
    rows: [
      {
        user_id: 7,
        email: "clerk@sml.lk",
        full_name: "Nimal Perera",
        roles: ["Accounts Clerk"],
        conflicts: [],
        overrides: [],
        pending_sensitive: 0,
        sensitive_access: [],
        last_login: null,
        review: null,
      },
    ],
  };
  mockApi({ "GET /api/v1/access-review/": { body: review } });
  const { unmount } = renderAt("/admin/access-review", <AccessReviewPage me={director} />);
  expect(await screen.findByRole("button", { name: "Confirm" })).toBeInTheDocument();
  expect(screen.getByText("Access review 2026-Q4")).toBeInTheDocument();
  unmount();

  renderAt("/admin/access-review", <AccessReviewPage me={admin} />);
  expect(await screen.findByText("Not reviewed yet")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Confirm" })).not.toBeInTheDocument();
});

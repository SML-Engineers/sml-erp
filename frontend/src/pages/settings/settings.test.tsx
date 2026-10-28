import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { CurrentUser } from "../../api/auth";
import type { Company, DivisionAdmin } from "../../api/organisation";
import { visibleMenu } from "../../layout/menu";
import { mockApi, renderAt, sampleUser } from "../../test-utils";
import CompanyPage from "./CompanyPage";
import DivisionsPage from "./DivisionsPage";

const admin: CurrentUser = {
  ...sampleUser,
  email: "admin@sml.lk",
  access: { areas: { settings: ["enter", "manage", "view"] }, actions: [], divisions: "all" },
};

const director: CurrentUser = {
  ...sampleUser,
  access: { areas: { settings: ["view"] }, actions: [], divisions: "all" },
};

const company: Company = {
  name: "SML Engineers",
  registration_no: "",
  tin: "",
  vat_no: "",
  address: "",
  phone: "",
  email: "",
  website: "",
  base_currency: "LKR",
  financial_year_start_month: 4,
  has_logo: false,
  updated_at: "2026-10-28T00:00:00Z",
};

const division = (extra: Partial<DivisionAdmin>): DivisionAdmin => ({
  id: 1,
  code: "WS",
  name: "Workshop",
  division_type: "production",
  tax_invoice_code: "",
  tax_invoice_code_in_use: false,
  is_active: true,
  in_use: false,
  first_used_at: null,
  users: 0,
  created_at: "2026-10-01T00:00:00Z",
  ...extra,
});

const divisions = [
  division({ id: 1, code: "WS", name: "Workshop", in_use: true, users: 3 }),
  division({ id: 2, code: "IM", name: "Plastic Injection Moulding", users: 2 }),
  division({ id: 3, code: "HO", name: "Head Office", division_type: "shared" }),
];

function fill(label: string, value: string, scope: HTMLElement = document.body) {
  fireEvent.change(within(scope).getByLabelText(label), { target: { value } });
}

// --- Menu --------------------------------------------------------------------------------

test("the Settings menu appears only for users with Settings access", () => {
  expect(visibleMenu(admin.access).map((s) => s.label)).toContain("menu.settings");
  expect(visibleMenu(sampleUser.access).map((s) => s.label)).not.toContain("menu.settings");
});

// --- Company profile ---------------------------------------------------------------------

test("the admin edits the company profile; the base currency cannot be changed", async () => {
  const api = mockApi({
    "GET /api/v1/company/": { body: company },
    "PUT /api/v1/company/": (sent) => ({ body: { ...company, ...(sent as object) } }),
  });
  renderAt("/settings/company", <CompanyPage me={admin} />);

  expect(await screen.findByLabelText("Company name")).toHaveValue("SML Engineers");
  expect(screen.getByLabelText(/Base currency/)).toBeDisabled();
  expect(screen.getByLabelText("Financial year starts in")).toHaveValue("4");

  fill("VAT registration no.", "123456789-7000");
  fill("Reason", "registration certificate");
  fireEvent.click(screen.getByRole("button", { name: "Save company profile" }));

  expect(await screen.findByText("Saved.")).toBeInTheDocument();
  const [, init] = api.mock.calls.find(([, i]) => i?.method === "PUT")!;
  const sent = JSON.parse(String(init!.body));
  expect(sent).toMatchObject({ vat_no: "123456789-7000", reason: "registration certificate" });
  expect(sent).not.toHaveProperty("base_currency");
});

test("users who can only view see the company profile read-only", async () => {
  mockApi({ "GET /api/v1/company/": { body: company } });
  renderAt("/settings/company", <CompanyPage me={director} />);

  expect(await screen.findByLabelText("Company name")).toBeDisabled();
  expect(screen.queryByRole("button", { name: "Save company profile" })).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Upload a logo")).not.toBeInTheDocument();
});

test("a refused logo shows the server's reason", async () => {
  mockApi({
    "GET /api/v1/company/": { body: company },
    "PUT /api/v1/company/logo/": {
      status: 400,
      body: { detail: "The logo must be a PNG or JPEG image." },
    },
  });
  renderAt("/settings/company", <CompanyPage me={admin} />);

  const input = await screen.findByLabelText("Upload a logo");
  fireEvent.change(input, { target: { files: [new File(["x"], "logo.gif")] } });

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "The logo must be a PNG or JPEG image.",
  );
});

// --- Divisions control panel -------------------------------------------------------------

test("the divisions list shows each division, its type and whether its code is fixed", async () => {
  mockApi({ "GET /api/v1/settings/divisions/": { body: divisions } });
  renderAt("/settings/divisions", <DivisionsPage me={director} />);

  const row = (await screen.findByText("Workshop")).closest("tr")!;
  expect(within(row).getByText("Fixed (used on documents)")).toBeInTheDocument();
  const ho = screen.getByText("Head Office").closest("tr")!;
  expect(within(ho).getByText("Shared")).toBeInTheDocument();
  expect(within(ho).getByText("Can still change")).toBeInTheDocument();
  // View-only users cannot add or edit.
  expect(screen.queryByText("Add a division")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
});

test("the admin adds a division and is told it can be used straight away", async () => {
  const added = division({ id: 4, code: "TS", name: "Tool Shop" });
  const api = mockApi({
    "GET /api/v1/settings/divisions/": { body: divisions },
    "POST /api/v1/settings/divisions/": { status: 201, body: added },
  });
  renderAt("/settings/divisions", <DivisionsPage me={admin} />);

  const panel = (await screen.findByText("Add a division")).closest("section")!;
  fill("Code", "ts", panel);
  fill("Name", "Tool Shop", panel);
  fireEvent.click(within(panel).getByRole("button", { name: "Add division" }));

  expect(
    await screen.findByText("Division TS Tool Shop added. It can be used straight away."),
  ).toBeInTheDocument();
  expect(api).toHaveBeenCalledWith(
    "/api/v1/settings/divisions/",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        code: "TS",
        name: "Tool Shop",
        division_type: "production",
        tax_invoice_code: "",
        reason: "",
      }),
    }),
  );
});

test("a division used on documents cannot have its code changed or be deleted", async () => {
  mockApi({ "GET /api/v1/settings/divisions/": { body: divisions } });
  renderAt("/settings/divisions", <DivisionsPage me={admin} />);

  fireEvent.click(await screen.findByRole("button", { name: "Edit division WS" }));
  const panel = screen.getByRole("region", { name: "Edit division WS" });
  expect(within(panel).getByLabelText("Code")).toBeDisabled();
  expect(within(panel).getByLabelText("Name")).toBeEnabled();
  expect(within(panel).queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
  expect(within(panel).getByRole("button", { name: "Deactivate" })).toBeInTheDocument();
});

test("an unused division with no users can be deleted", async () => {
  mockApi({ "GET /api/v1/settings/divisions/": { body: divisions } });
  renderAt("/settings/divisions", <DivisionsPage me={admin} />);

  fireEvent.click(await screen.findByRole("button", { name: "Edit division HO" }));
  const panel = screen.getByRole("region", { name: "Edit division HO" });
  expect(within(panel).getByLabelText("Code")).toBeEnabled();
  expect(within(panel).getByRole("button", { name: "Delete" })).toBeInTheDocument();
});

test("the server's refusal is shown, e.g. deactivating without a reason", async () => {
  const api = mockApi({
    "GET /api/v1/settings/divisions/": { body: divisions },
    "PATCH /api/v1/settings/divisions/2/": {
      status: 400,
      body: { detail: "Give a reason for deactivating the division." },
    },
  });
  renderAt("/settings/divisions", <DivisionsPage me={admin} />);

  fireEvent.click(await screen.findByRole("button", { name: "Edit division IM" }));
  const panel = screen.getByRole("region", { name: "Edit division IM" });
  fireEvent.click(within(panel).getByRole("button", { name: "Deactivate" }));

  expect(await within(panel).findByRole("alert")).toHaveTextContent(
    "Give a reason for deactivating the division.",
  );
  expect(api).toHaveBeenCalledWith(
    "/api/v1/settings/divisions/2/",
    expect.objectContaining({ method: "PATCH" }),
  );
});

test("the admin sets a division's tax invoice code; a used one is locked", async () => {
  const withCodes = [
    { ...divisions[0], tax_invoice_code: "W1", tax_invoice_code_in_use: true },
    divisions[1],
    divisions[2],
  ];
  const api = mockApi({
    "GET /api/v1/settings/divisions/": { body: withCodes },
    "PATCH /api/v1/settings/divisions/2/": (sent) => ({
      body: { ...divisions[1], ...(sent as object) },
    }),
  });
  renderAt("/settings/divisions", <DivisionsPage me={admin} />);

  const ws = (await screen.findByText("Workshop")).closest("tr")!;
  expect(within(ws).getByText("W1")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Edit division WS" }));
  let panel = screen.getByRole("region", { name: "Edit division WS" });
  expect(within(panel).getByLabelText("Tax invoice code")).toBeDisabled();
  fireEvent.click(within(panel).getByRole("button", { name: "Cancel" }));

  fireEvent.click(screen.getByRole("button", { name: "Edit division IM" }));
  panel = screen.getByRole("region", { name: "Edit division IM" });
  fill("Tax invoice code", "p1", panel);
  fireEvent.click(within(panel).getByRole("button", { name: "Save" }));

  await screen.findByRole("button", { name: "Edit division IM" });
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      "/api/v1/settings/divisions/2/",
      expect.objectContaining({ method: "PATCH" }),
    ),
  );
  const [, init] = api.mock.calls.find(([, i]) => i?.method === "PATCH")!;
  expect(JSON.parse(String(init!.body))).toMatchObject({ code: "IM", tax_invoice_code: "P1" });
});

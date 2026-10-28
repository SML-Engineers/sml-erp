import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { CurrentUser } from "../../api/auth";
import type { Machine, Section } from "../../api/factory";
import type { DivisionAdmin } from "../../api/organisation";
import { mockApi, renderAt, sampleUser } from "../../test-utils";
import FactoryPage from "./FactoryPage";

const admin: CurrentUser = {
  ...sampleUser,
  access: { areas: { settings: ["enter", "manage", "view"] }, actions: [], divisions: "all" },
};

const director: CurrentUser = {
  ...sampleUser,
  access: { areas: { settings: ["view"] }, actions: [], divisions: "all" },
};

const division = (code: string, name: string): DivisionAdmin => ({
  id: code === "WS" ? 1 : 2,
  code,
  name,
  division_type: "production",
  tax_invoice_code: "",
  tax_invoice_code_in_use: false,
  is_active: true,
  in_use: false,
  first_used_at: null,
  users: 0,
  created_at: "2026-10-01T00:00:00Z",
});

const section = (id: number, code: string, name: string, extra: Partial<Section> = {}): Section => ({
  id,
  code,
  name,
  division: "WS",
  section_type: "machining",
  category: "manual",
  supervisors: [],
  is_active: true,
  in_use: false,
  machine_count: 0,
  ...extra,
});

const moulder: Machine = {
  id: 1,
  code: "IMM-01",
  name: "Haitian 250",
  section: "IM-MLD",
  division: "IM",
  make: "Haitian",
  model: "MA2500",
  serial_no: "",
  year: 2019,
  status: "active",
  notes: "",
  clamping_force_t: "250.0",
  max_shot_weight_g: "455.5",
  screw_diameter_mm: null,
  tie_bar_h_mm: null,
  tie_bar_v_mm: null,
  max_mould_height_mm: null,
  max_mould_thickness_mm: null,
  in_use: true,
  has_photo: false,
  current_rate: "3200.50",
};

const baseApi = {
  "GET /api/v1/settings/divisions/": {
    body: [division("WS", "Workshop"), division("IM", "Plastic Injection Moulding")],
  },
  "GET /api/v1/settings/sections/": {
    body: [
      section(1, "M-MIL", "Manual Milling"),
      section(2, "C-LAT", "CNC Lathe", { category: "cnc" }),
      section(3, "IM-MLD", "Injection Moulding Machines", {
        division: "IM",
        section_type: "moulding",
        category: "",
        machine_count: 1,
      }),
    ],
  },
  "GET /api/v1/settings/machines/": { body: [moulder] },
  "GET /api/v1/settings/machines/1/rates/": {
    body: [
      {
        id: 5,
        effective_from: "2026-10-01",
        rate: "3200.50",
        reason: "costing",
        created_by: "admin@sml.lk",
        created_at: "2026-10-01T00:00:00Z",
        in_force: true,
      },
    ],
  },
  "GET /api/v1/users/": { body: [] },
};

test("the tree shows divisions, sections and machines, and search narrows it", async () => {
  mockApi(baseApi);
  renderAt("/settings/factory", <FactoryPage me={director} />);

  const tree = await screen.findByRole("navigation", { name: "Factory structure" });
  expect(within(tree).getByText("WS Workshop")).toBeInTheDocument();
  expect(within(tree).getByRole("button", { name: "M-MIL Manual Milling" })).toBeInTheDocument();
  expect(within(tree).getByRole("button", { name: "IMM-01 Haitian 250" })).toBeInTheDocument();

  fireEvent.change(within(tree).getByLabelText("Search"), { target: { value: "haitian" } });
  expect(within(tree).queryByRole("button", { name: "M-MIL Manual Milling" })).not.toBeInTheDocument();
  expect(within(tree).getByRole("button", { name: "IMM-01 Haitian 250" })).toBeInTheDocument();
  // View only: nothing to add.
  expect(screen.queryByRole("button", { name: "Add machine" })).not.toBeInTheDocument();
});

test("a used moulding machine shows its size and rate, with the code locked", async () => {
  mockApi(baseApi);
  renderAt("/settings/factory", <FactoryPage me={admin} />);

  fireEvent.click(await screen.findByRole("button", { name: "IMM-01 Haitian 250" }));
  const form = screen.getByRole("region", { name: "Machine IMM-01" });
  expect(within(form).getByLabelText("Code")).toBeDisabled();
  expect(within(form).getByLabelText("Clamping force (t)")).toHaveValue(250);
  expect(within(form).queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
  expect(await screen.findByText("3,200.50")).toBeInTheDocument();
});

test("the admin adds a machine to a section", async () => {
  const api = mockApi({
    ...baseApi,
    "POST /api/v1/settings/machines/": (sent) => ({
      status: 201,
      body: { ...moulder, ...(sent as object), id: 2, in_use: false },
    }),
  });
  renderAt("/settings/factory", <FactoryPage me={admin} />);

  fireEvent.click(await screen.findByRole("button", { name: "M-MIL Manual Milling" }));
  fireEvent.click(screen.getByRole("button", { name: "Add machine" }));
  const form = screen.getByRole("region", { name: "Add machine" });
  fireEvent.change(within(form).getByLabelText("Code"), { target: { value: "m-mil-01" } });
  fireEvent.change(within(form).getByLabelText("Name"), { target: { value: "Milling 1" } });
  // Not a moulding section: no moulding size fields.
  expect(within(form).queryByLabelText("Clamping force (t)")).not.toBeInTheDocument();
  fireEvent.click(within(form).getByRole("button", { name: "Save" }));

  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      "/api/v1/settings/machines/",
      expect.objectContaining({ method: "POST" }),
    ),
  );
  const [, init] = api.mock.calls.find(([, i]) => i?.method === "POST")!;
  expect(JSON.parse(String(init!.body))).toMatchObject({
    code: "M-MIL-01",
    name: "Milling 1",
    section: "M-MIL",
    status: "active",
    year: null,
    clamping_force_t: null,
  });
});

test("an import is checked first, and refused rows are listed", async () => {
  let calls = 0;
  mockApi({
    ...baseApi,
    "POST /api/v1/settings/factory/import/": () => {
      calls += 1;
      return calls === 1
        ? {
            body: {
              dry_run: true,
              sections_created: 0,
              sections_updated: 3,
              machines_created: 8,
              machines_updated: 0,
            },
          }
        : {
            status: 400,
            body: {
              detail: "Nothing was imported.",
              errors: ["Machines row 4: Unknown section 'NOPE'."],
            },
          };
    },
  });
  renderAt("/settings/factory", <FactoryPage me={admin} />);

  fireEvent.click(await screen.findByRole("button", { name: "Import from Excel" }));
  const panel = screen.getByRole("region", { name: "Import from Excel" });
  fireEvent.change(within(panel).getByLabelText("Excel file (.xlsx)"), {
    target: { files: [new File(["x"], "machines.xlsx")] },
  });
  fireEvent.click(within(panel).getByRole("button", { name: "Check file" }));
  expect(await within(panel).findByRole("status")).toHaveTextContent(
    "add 8 and update 0 machines",
  );

  fireEvent.click(within(panel).getByRole("button", { name: "Import" }));
  const alert = await within(panel).findByRole("alert");
  expect(alert).toHaveTextContent("Nothing was imported.");
  expect(alert).toHaveTextContent("Machines row 4: Unknown section 'NOPE'.");
});

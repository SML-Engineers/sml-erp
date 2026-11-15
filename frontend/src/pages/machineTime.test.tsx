import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { MachineBoard, MachineJob, StartOptions } from "../api/machineJobs";
import { mockApi, renderAt } from "../test-utils";
import MachineTimePage from "./MachineTimePage";

const running: MachineJob = {
  id: 7,
  machine: "M-LAT-01",
  section: "M-LAT",
  kind: "job",
  job: "JO26110001",
  operation: 20,
  operation_name: "Turn",
  order: null,
  item: null,
  mould: null,
  operator: "Sunil Perera",
  drawing_no: "DR-100",
  description: "Turn",
  notes: "",
  started_at: "2026-11-15T08:00:00+05:30",
  started_by: "Team Leader",
  ended_at: null,
  ended_by: null,
  minutes: 90,
  hours: "1.50",
  completed: null,
  rejected: null,
  start_counter: null,
  end_counter: null,
  second_allowed_by: null,
  second_reason: "",
};

const board: MachineBoard = {
  now: "2026-11-15T09:30:00+05:30",
  can_enter: true,
  can_allow_second: false,
  machines: [
    { code: "M-LAT-01", name: "Lathe 1", section: "M-LAT", section_type: "machining", status: "running", jobs: [running] },
    { code: "M-LAT-02", name: "Lathe 2", section: "M-LAT", section_type: "machining", status: "idle", jobs: [] },
    { code: "IMM-250", name: "Haitian 250 t", section: "IM-MLD", section_type: "moulding", status: "maintenance", jobs: [] },
  ],
};

const options: StartOptions = {
  kind: "job",
  orders: [],
  jobs: [
    {
      number: "JO26110001",
      item: "SH-100",
      description: "",
      drawing_no: "DR-100",
      operations: [
        { seq: 10, name: "Cut", card: "JO26110001/10", here: false },
        { seq: 20, name: "Turn", card: "JO26110001/20", here: true },
      ],
    },
  ],
};

function api(more = {}) {
  return {
    "GET /api/v1/machine-jobs/board/": { body: board },
    "GET /api/v1/machine-jobs/": { body: { results: [running] } },
    ...more,
  };
}

test("the board shows what every machine is doing", async () => {
  mockApi(api());
  renderAt("/machine-time", <MachineTimePage />);
  const lathe = await screen.findByRole("article", { name: "Machine M-LAT-01" });
  expect(within(lathe).getByText("Running")).toBeInTheDocument();
  expect(within(lathe).getByText(/JO26110001\/20 Turn/)).toBeInTheDocument();
  expect(within(lathe).getByText(/since 08:00/)).toBeInTheDocument();
  expect(within(lathe).getByText("Operator: Sunil Perera")).toBeInTheDocument();
  // Running, and nobody here may allow a second job: only Finish.
  expect(within(lathe).queryByRole("button", { name: "Start job" })).not.toBeInTheDocument();
  const idle = screen.getByRole("article", { name: "Machine M-LAT-02" });
  expect(within(idle).getByText("Idle")).toBeInTheDocument();
  const press = screen.getByRole("article", { name: "Machine IMM-250" });
  expect(within(press).getByText("Under maintenance")).toBeInTheDocument();
  expect(within(press).queryByRole("button")).not.toBeInTheDocument();
});

test("the team leader starts a job from the job card list, with the drawing from the job", async () => {
  const calls = mockApi(
    api({
      "GET /api/v1/machine-jobs/options/?machine=M-LAT-02": { body: options },
      "POST /api/v1/machine-jobs/": { status: 201, body: { ...running, id: 8, machine: "M-LAT-02" } },
    }),
  );
  renderAt("/machine-time", <MachineTimePage />);
  const idle = await screen.findByRole("article", { name: "Machine M-LAT-02" });
  fireEvent.click(within(idle).getByRole("button", { name: "Start job" }));
  const form = await screen.findByRole("region", { name: "Start a job on M-LAT-02" });
  await within(form).findByRole("option", { name: /JO26110001\/20 Turn ★/ });
  fireEvent.change(within(form).getByLabelText(/Job and operation/), { target: { value: "JO26110001/20" } });
  expect(within(form).getByLabelText("Drawing no. (optional)")).toHaveValue("DR-100");
  fireEvent.change(within(form).getByLabelText("Operator no. (optional)"), { target: { value: "E0012" } });
  fireEvent.click(within(form).getByRole("button", { name: "Start job" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/machine-jobs/", expect.objectContaining({ method: "POST" })));
  const [, init] = calls.mock.calls.find(([url, i]) => url === "/api/v1/machine-jobs/" && i?.method === "POST")!;
  expect(JSON.parse(String(init!.body))).toEqual({
    machine: "M-LAT-02",
    job: "JO26110001/20",
    description: "",
    operator: "E0012",
    notes: "",
  });
  await waitFor(() => expect(screen.queryByRole("region", { name: "Start a job on M-LAT-02" })).not.toBeInTheDocument());
});

test("finishing a job asks for the pieces and shows the server's refusal", async () => {
  const calls = mockApi(
    api({
      "POST /api/v1/machine-jobs/7/finish/": { status: 400, body: { detail: "The finish must be after the start." } },
    }),
  );
  renderAt("/machine-time", <MachineTimePage />);
  const lathe = await screen.findByRole("article", { name: "Machine M-LAT-01" });
  fireEvent.click(within(lathe).getByRole("button", { name: "Finish job" }));
  const form = await screen.findByRole("region", { name: "Finish the job on M-LAT-01" });
  fireEvent.change(within(form).getByLabelText("Pieces completed"), { target: { value: "12" } });
  fireEvent.change(within(form).getByLabelText("Pieces rejected"), { target: { value: "1" } });
  fireEvent.click(within(form).getByRole("button", { name: "Finish job" }));
  expect(await within(form).findByRole("alert")).toHaveTextContent("The finish must be after the start.");
  const [, init] = calls.mock.calls.find(([url]) => url === "/api/v1/machine-jobs/7/finish/")!;
  expect(JSON.parse(String(init!.body))).toEqual({ completed: "12", rejected: "1", notes: "" });
});

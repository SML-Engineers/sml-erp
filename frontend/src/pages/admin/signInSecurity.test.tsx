import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import { mockApi, renderAt } from "../../test-utils";
import SignInSecurityPage from "./SignInSecurityPage";

const URL = "/api/v1/access/sign-in-security/";

test("the Admin switches two-factor sign-in off with a reason, and the page warns while it is off", async () => {
  // Owner, 12 Nov 2026: off while testing, on before go-live.
  const calls = mockApi({
    [`GET ${URL}`]: { body: { two_factor_on: true, activity_log_level: "sensitive" } },
    [`PUT ${URL}`]: { body: { two_factor_on: false, activity_log_level: "sensitive" } },
  });
  renderAt("/admin/sign-in-security", <SignInSecurityPage canChange />);
  expect(await screen.findByRole("status")).toHaveTextContent("On: an authenticator code is asked for");
  const button = screen.getByRole("button", { name: "Switch two-factor sign-in off" });
  expect(button).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Reason for the change"), { target: { value: "Testing on the PC" } });
  fireEvent.click(button);
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      URL,
      expect.objectContaining({ method: "PUT", body: JSON.stringify({ two_factor_on: false, reason: "Testing on the PC" }) }),
    ),
  );
  expect(await screen.findByText(/Switch this on before go-live/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Switch two-factor sign-in on" })).toBeInTheDocument();
});

test("someone who may only look sees the state but no switch", async () => {
  mockApi({ [`GET ${URL}`]: { body: { two_factor_on: false, activity_log_level: "sensitive" } } });
  renderAt("/admin/sign-in-security", <SignInSecurityPage canChange={false} />);
  expect(await screen.findByRole("status")).toHaveTextContent("Off");
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
  // The log level is shown but cannot be changed.
  expect(screen.getByRole("radio", { name: /Sensitive \(recommended\)/ })).toBeChecked();
  expect(screen.getByRole("radio", { name: /Everything/ })).toBeDisabled();
});

test("the Admin changes the activity log level with a reason", async () => {
  // Owner, 14 Nov 2026: changes and sign-ins only / sensitive (default) / everything.
  const calls = mockApi({
    [`GET ${URL}`]: { body: { two_factor_on: true, activity_log_level: "sensitive" } },
    [`PUT ${URL}`]: { body: { two_factor_on: true, activity_log_level: "everything" } },
  });
  renderAt("/admin/sign-in-security", <SignInSecurityPage canChange />);
  const panel = await screen.findByRole("region", { name: "Activity log level" });
  expect(within(panel).getByRole("radio", { name: /Sensitive \(recommended\) \(in force\)/ })).toBeChecked();
  expect(within(panel).queryByRole("button", { name: "Change the level" })).not.toBeInTheDocument();

  fireEvent.click(within(panel).getByRole("radio", { name: /Everything/ }));
  const save = within(panel).getByRole("button", { name: "Change the level" });
  expect(save).toBeDisabled();
  fireEvent.change(within(panel).getByLabelText("Reason for the change"), { target: { value: "Audit month" } });
  fireEvent.click(save);
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      URL,
      expect.objectContaining({ method: "PUT", body: JSON.stringify({ activity_log_level: "everything", reason: "Audit month" }) }),
    ),
  );
  expect(await within(panel).findByRole("radio", { name: /Everything \(in force\)/ })).toBeChecked();
});

const NOTICE_URL = "/api/v1/access/notice/";
const EN = "Entering false information into the system is a punishable offence.";
const SI = "පද්ධතියට අසත්‍ය තොරතුරු ඇතුළත් කිරීම දඬුවම් ලැබිය හැකි වරදකි.";
const noticeOff = {
  current: { show: false, text_en: "", text_si: "" },
  defaults: { text_en: EN, text_si: SI },
  in_force: null,
  waiting: null,
  history: [],
};

test("the Admin asks to show the top-bar notice with a reason (owner, 21 Nov 2026)", async () => {
  const calls = mockApi({
    [`GET ${URL}`]: { body: { two_factor_on: true, activity_log_level: "sensitive" } },
    [`GET ${NOTICE_URL}`]: { body: noticeOff },
    [`POST ${NOTICE_URL}`]: { status: 201, body: {} },
  });
  renderAt("/admin/sign-in-security", <SignInSecurityPage canChange />);
  const panel = await screen.findByRole("region", { name: "Top-bar notice" });
  expect(within(panel).getByRole("status")).toHaveTextContent("The notice is not shown.");
  // The suggested words are filled in, in both languages.
  expect(within(panel).getByLabelText("English line")).toHaveValue(EN);
  expect(within(panel).getByLabelText("Sinhala line")).toHaveValue(SI);
  const button = within(panel).getByRole("button", { name: "Ask to show the notice" });
  expect(button).toBeDisabled();
  fireEvent.change(within(panel).getByLabelText("Reason for the change"), { target: { value: "Staff reminder" } });
  fireEvent.click(button);
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      NOTICE_URL,
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ show: true, text_en: EN, text_si: SI, reason: "Staff reminder" }),
      }),
    ),
  );
  expect(await within(panel).findByText("Asked. The Director has been told.")).toBeInTheDocument();
});

test("a waiting change shows who asked, and the Admin can withdraw it", async () => {
  const waiting = {
    id: 3,
    show: true,
    text_en: EN,
    text_si: SI,
    reason: "Staff reminder",
    requested_by: "Peduru Somarathna",
    requested_at: "2026-11-21T10:00:00Z",
    status: "waiting",
    status_label: "Waiting for the Director",
    decided_by: null,
    decided_at: null,
    decision_reason: "",
    can_decide: false,
  };
  const calls = mockApi({
    [`GET ${URL}`]: { body: { two_factor_on: true, activity_log_level: "sensitive" } },
    [`GET ${NOTICE_URL}`]: { body: { ...noticeOff, waiting, history: [waiting] } },
    [`POST ${NOTICE_URL}3/withdraw/`]: { body: { ...waiting, status: "withdrawn" } },
  });
  renderAt("/admin/sign-in-security", <SignInSecurityPage canChange />);
  const panel = await screen.findByRole("region", { name: "Top-bar notice" });
  expect(within(panel).getByLabelText("Waiting for the Director")).toHaveTextContent("Peduru Somarathna");
  expect(within(panel).queryByRole("button", { name: "Ask to show the notice" })).not.toBeInTheDocument();
  fireEvent.click(within(panel).getByRole("button", { name: "Withdraw the request" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith(`${NOTICE_URL}3/withdraw/`, expect.objectContaining({ method: "POST" })));
});

test("someone who may only look sees the notice state but cannot ask", async () => {
  mockApi({
    [`GET ${URL}`]: { body: { two_factor_on: true, activity_log_level: "sensitive" } },
    [`GET ${NOTICE_URL}`]: {
      body: { ...noticeOff, current: { show: true, text_en: EN, text_si: SI }, in_force: { text_en: EN, text_si: SI } },
    },
  });
  renderAt("/admin/sign-in-security", <SignInSecurityPage canChange={false} />);
  const panel = await screen.findByRole("region", { name: "Top-bar notice" });
  expect(within(panel).getByRole("status")).toHaveTextContent("The notice is shown.");
  expect(within(panel).getByText(SI)).toBeInTheDocument();
  expect(within(panel).queryByRole("button")).not.toBeInTheDocument();
});

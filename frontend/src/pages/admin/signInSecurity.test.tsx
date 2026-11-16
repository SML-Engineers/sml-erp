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

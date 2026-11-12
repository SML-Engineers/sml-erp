import { fireEvent, screen, waitFor } from "@testing-library/react";

import { mockApi, renderAt } from "../../test-utils";
import SignInSecurityPage from "./SignInSecurityPage";

const URL = "/api/v1/access/sign-in-security/";

test("the Admin switches two-factor sign-in off with a reason, and the page warns while it is off", async () => {
  // Owner, 12 Nov 2026: off while testing, on before go-live.
  const calls = mockApi({
    [`GET ${URL}`]: { body: { two_factor_on: true } },
    [`PUT ${URL}`]: { body: { two_factor_on: false } },
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
  mockApi({ [`GET ${URL}`]: { body: { two_factor_on: false } } });
  renderAt("/admin/sign-in-security", <SignInSecurityPage canChange={false} />);
  expect(await screen.findByRole("status")).toHaveTextContent("Off");
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

import { fireEvent, screen } from "@testing-library/react";

import { mockApi, renderAt, sampleUser } from "../test-utils";
import LoginPage from "./LoginPage";

function fill(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

test("signs in and goes to the home page", async () => {
  mockApi({ "POST /api/v1/auth/login/": { body: { status: "ok", user: sampleUser } } });
  renderAt("/login", <LoginPage />);

  fill("Email", "director@sml.lk");
  fill("Password", "Correct-Horse-42");
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

  expect(await screen.findByText("Home page")).toBeInTheDocument();
});

test("shows the server's message when sign-in fails", async () => {
  mockApi({
    "POST /api/v1/auth/login/": {
      status: 400,
      body: { status: "invalid", detail: "The email, password or code is not correct." },
    },
  });
  renderAt("/login", <LoginPage />);

  fill("Email", "x@sml.lk");
  fill("Password", "nope");
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("The email, password or code is not correct.");
});

test("asks for the two-factor code after the password", async () => {
  const api = mockApi({
    "POST /api/v1/auth/login/": { body: { status: "two_factor_required" } },
    "POST /api/v1/auth/login/verify/": (sent) =>
      (sent as { code: string }).code === "123456"
        ? { body: { status: "ok", user: sampleUser } }
        : { status: 400, body: { detail: "Wrong code" } },
  });
  renderAt("/login", <LoginPage />);

  fill("Email", "director@sml.lk");
  fill("Password", "Correct-Horse-42");
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

  await screen.findByLabelText("Code");
  fill("Code", "123456");
  fireEvent.click(screen.getByRole("button", { name: "Verify" }));

  expect(await screen.findByText("Home page")).toBeInTheDocument();
  expect(api).toHaveBeenCalledWith(
    "/api/v1/auth/login/verify/",
    expect.objectContaining({
      method: "POST",
      headers: expect.objectContaining({ "X-CSRFToken": "test-token" }),
    }),
  );
});

test("says why when another computer's sign-in ended this one", async () => {
  mockApi({
    "GET /api/v1/auth/me/": { body: { authenticated: false, two_factor_pending: false, signed_out_reason: "computer" } },
  });
  renderAt("/login", <LoginPage />);

  expect(await screen.findByRole("status", { name: "Why you were signed out" })).toHaveTextContent(
    "You were signed out because you signed in on another computer.",
  );
});

test("says why when another phone's sign-in ended this one", async () => {
  mockApi({
    "GET /api/v1/auth/me/": { body: { authenticated: false, two_factor_pending: false, signed_out_reason: "phone" } },
  });
  renderAt("/login", <LoginPage />);

  expect(await screen.findByRole("status", { name: "Why you were signed out" })).toHaveTextContent(
    "You were signed out because you signed in on another phone.",
  );
});

test("shows no reason after an ordinary sign-out", async () => {
  mockApi({
    "GET /api/v1/auth/me/": { body: { authenticated: false, two_factor_pending: false, signed_out_reason: null } },
  });
  renderAt("/login", <LoginPage />);

  expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
  expect(screen.queryByRole("status", { name: "Why you were signed out" })).not.toBeInTheDocument();
});

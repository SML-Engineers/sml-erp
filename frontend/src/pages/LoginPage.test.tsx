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

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "The email, password or code is not correct.",
  );
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

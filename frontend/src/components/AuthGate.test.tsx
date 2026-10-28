import { screen } from "@testing-library/react";

import { mockApi, renderAt, sampleUser } from "../test-utils";
import AuthGate from "./AuthGate";

const page = (
  <AuthGate>{(user) => <p>Protected content for {user.full_name}</p>}</AuthGate>
);

test("sends visitors who are not signed in to the login page", async () => {
  mockApi({
    "GET /api/v1/auth/me/": { body: { authenticated: false, two_factor_pending: false } },
  });
  renderAt("/reports", page);
  expect(await screen.findByText("Login page")).toBeInTheDocument();
});

test("holds users until they set up two-factor sign-in", async () => {
  mockApi({
    "GET /api/v1/auth/me/": {
      body: {
        authenticated: true,
        user: { ...sampleUser, requirements: ["two_factor_setup_required"] },
      },
    },
  });
  renderAt("/reports", page);
  expect(await screen.findByText("Two-factor page")).toBeInTheDocument();
});

test("holds users until they change a temporary password", async () => {
  mockApi({
    "GET /api/v1/auth/me/": {
      body: {
        authenticated: true,
        user: { ...sampleUser, requirements: ["password_change_required"] },
      },
    },
  });
  renderAt("/reports", page);
  expect(await screen.findByText("Password page")).toBeInTheDocument();
});

test("shows the page to a fully signed-in user", async () => {
  mockApi({ "GET /api/v1/auth/me/": { body: { authenticated: true, user: sampleUser } } });
  renderAt("/reports", page);
  expect(await screen.findByText("Protected content for Mewantha")).toBeInTheDocument();
});

import { fireEvent, screen } from "@testing-library/react";

import { mockApi, renderAt, sampleUser } from "../test-utils";
import HomePage from "./HomePage";

test("welcomes the user and shows the system status", async () => {
  mockApi({
    "GET /api/v1/health/": { body: { status: "ok", database: "ok", version: "0.1.0" } },
  });
  renderAt("/dashboard", <HomePage user={sampleUser} />);

  expect(screen.getByText("Welcome, Mewantha")).toBeInTheDocument();
  expect(await screen.findByText("System status: OK")).toBeInTheDocument();
  expect(screen.getByText("Version 0.1.0")).toBeInTheDocument();
});

test("says when the database is not reachable", async () => {
  mockApi({
    "GET /api/v1/health/": {
      status: 503,
      body: { status: "degraded", database: "unavailable", version: "0.1.0" },
    },
  });
  renderAt("/dashboard", <HomePage user={sampleUser} />);

  expect(
    await screen.findByText("System status: the database is not reachable"),
  ).toBeInTheDocument();
});

test("signs out and returns to the login page", async () => {
  mockApi({
    "GET /api/v1/health/": { body: { status: "ok", database: "ok", version: "0.1.0" } },
    "POST /api/v1/auth/logout/": { body: { status: "signed_out" } },
  });
  renderAt("/dashboard", <HomePage user={sampleUser} />);

  fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
  expect(await screen.findByText("Login page")).toBeInTheDocument();
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

import HomePage from "./HomePage";

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <HomePage />
    </QueryClientProvider>,
  );
}

function mockFetch(status: number, body: unknown) {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

test("shows OK and the version when the API is healthy", async () => {
  mockFetch(200, { status: "ok", database: "ok", version: "0.1.0" });
  renderPage();

  expect(await screen.findByText("System status: OK")).toBeInTheDocument();
  expect(screen.getByText("Version 0.1.0")).toBeInTheDocument();
  expect(globalThis.fetch).toHaveBeenCalledWith("/api/v1/health/", expect.anything());
});

test("shows an error when the server cannot be reached", async () => {
  vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
  renderPage();

  expect(await screen.findByText("Cannot reach the server")).toBeInTheDocument();
});

test("says the database is unreachable when the API reports it is down", async () => {
  mockFetch(503, { status: "degraded", database: "unavailable", version: "0.1.0" });
  renderPage();

  expect(
    await screen.findByText("System status: the database is not reachable"),
  ).toBeInTheDocument();
});

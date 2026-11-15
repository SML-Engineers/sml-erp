import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";

import type { CurrentUser } from "./api/auth";
import App from "./App";
import { mockApi, sampleUser } from "./test-utils";

const director: CurrentUser = {
  ...sampleUser,
  full_name: "Ruwan Jayasinghe",
  access: { areas: { dashboard: ["view"], stores: ["approve", "view"] }, actions: [], divisions: "all" },
};

// A stock adjustment notification sent before 16 Nov 2026 links to /stock-adjustments/<id>,
// which had no page. It now opens Stores work on the Adjustments tab, where the Director
// approves it (owner, 16 Nov 2026: a notification leads to a page with the action on it).
test("an old stock adjustment link opens the Adjustments tab", async () => {
  mockApi({
    "GET /api/v1/auth/me/": { body: { authenticated: true, user: director } },
    "GET /api/v1/stock-adjustments/": { body: [] },
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/stock-adjustments/5"]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(await screen.findByRole("heading", { name: "Stores work" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "Adjustments and write-offs" })).toHaveAttribute("aria-selected", "true");
});

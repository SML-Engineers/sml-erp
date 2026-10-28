import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { vi } from "vitest";

import type { CurrentUser } from "./api/auth";

type Reply = { status?: number; body: unknown };
type ApiRoutes = Record<string, Reply | ((body: unknown) => Reply)>;

/** Fake the API: keys are "METHOD /path", e.g. "POST /api/v1/auth/login/". */
export function mockApi(routes: ApiRoutes) {
  document.cookie = "csrftoken=test-token";
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const method = (init?.method ?? "GET").toUpperCase();
    const route = routes[`${method} ${url}`];
    if (!route) throw new Error(`Unexpected request: ${method} ${url}`);
    const sent = init?.body ? JSON.parse(String(init.body)) : undefined;
    const reply = typeof route === "function" ? route(sent) : route;
    return new Response(JSON.stringify(reply.body), {
      status: reply.status ?? 200,
      headers: { "Content-Type": "application/json" },
    });
  });
}

/** Render `element` at `path`, with simple stand-ins for the other pages. */
export function renderAt(path: string, element: ReactNode, routePath = path) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path={routePath} element={element} />
          <Route path="/" element={<p>Home page</p>} />
          <Route path="/login" element={<p>Login page</p>} />
          <Route path="/account/two-factor" element={<p>Two-factor page</p>} />
          <Route path="/account/password" element={<p>Password page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

export const sampleUser: CurrentUser = {
  email: "director@sml.lk",
  full_name: "Mewantha",
  two_factor_enabled: true,
  two_factor_required: true,
  requirements: [],
  access: { areas: { dashboard: ["view"] }, actions: [], divisions: "all" },
};

// All calls go to the Django API under /api/v1/ (CLAUDE.md: the frontend uses only this API).
export const API_BASE = "/api/v1";

export class ApiError extends Error {
  constructor(
    public status: number,
    public body: unknown,
  ) {
    super(`API request failed with status ${status}`);
  }

  /** The server's explanation, ready to show to the user. */
  get detail(): string | undefined {
    const detail = (this.body as { detail?: unknown } | null)?.detail;
    if (Array.isArray(detail)) return detail.join(" ");
    return typeof detail === "string" ? detail : undefined;
  }
}

function readCookie(name: string): string | undefined {
  return document.cookie
    .split("; ")
    .find((part) => part.startsWith(`${name}=`))
    ?.split("=")[1];
}

let csrfReady: Promise<void> | null = null;

/** Django sets the CSRF cookie on this call; every change sends it back as a header. */
export function ensureCsrf(): Promise<void> {
  if (readCookie("csrftoken")) return Promise.resolve();
  csrfReady ??= fetch(`${API_BASE}/auth/csrf/`, { credentials: "same-origin" }).then(() => {
    csrfReady = null;
  });
  return csrfReady;
}

async function parse<T>(response: Response): Promise<T> {
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, body);
  return body as T;
}

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  });
  return parse<T>(response);
}

export function apiPost<T>(path: string, data?: unknown): Promise<T> {
  return apiSend<T>("POST", path, data);
}

/** Any change (POST, PUT, PATCH, DELETE), with the CSRF token Django requires. */
export async function apiSend<T>(
  method: "POST" | "PUT" | "PATCH" | "DELETE",
  path: string,
  data?: unknown,
): Promise<T> {
  await ensureCsrf();
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-CSRFToken": readCookie("csrftoken") ?? "",
    },
    body: data === undefined ? undefined : JSON.stringify(data),
  });
  return parse<T>(response);
}

/** Upload files (multipart form). The browser sets the Content-Type with its boundary. */
export async function apiUpload<T>(path: string, form: FormData, method: "POST" | "PUT" = "PUT") {
  await ensureCsrf();
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    credentials: "same-origin",
    headers: { Accept: "application/json", "X-CSRFToken": readCookie("csrftoken") ?? "" },
    body: form,
  });
  return parse<T>(response);
}

import { ApiError, apiGet } from "./client";

export interface Health {
  status: "ok" | "degraded";
  database: "ok" | "unavailable";
  version: string;
}

// A 503 from the health endpoint still carries a useful answer: the API is up but the
// database is not. Only other failures count as "cannot reach the server".
export async function getHealth(): Promise<Health> {
  try {
    return await apiGet<Health>("/health/");
  } catch (error) {
    if (error instanceof ApiError && error.status === 503 && error.body) {
      return error.body as Health;
    }
    throw error;
  }
}

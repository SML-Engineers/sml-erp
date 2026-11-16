import { apiGet, apiSend } from "./client";

export type LogLevel = "changes" | "sensitive" | "everything";

/** Security and logging: the company-wide two-factor switch (owner, 12 Nov 2026) and the
 * activity log level (owner, 14 Nov 2026). */
export interface SignInSecurity {
  two_factor_on: boolean;
  activity_log_level: LogLevel;
}

export const signInSecurityKey = ["sign-in-security"] as const;

export function getSignInSecurity() {
  return apiGet<SignInSecurity>("/access/sign-in-security/");
}

export function setSignInSecurity(two_factor_on: boolean, reason: string) {
  return apiSend<SignInSecurity>("PUT", "/access/sign-in-security/", { two_factor_on, reason });
}

export function setLogLevel(activity_log_level: LogLevel, reason: string) {
  return apiSend<SignInSecurity>("PUT", "/access/sign-in-security/", { activity_log_level, reason });
}

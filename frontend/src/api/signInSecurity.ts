import { apiGet, apiSend } from "./client";

/** The company-wide two-factor switch (owner, 12 Nov 2026). */
export interface SignInSecurity {
  two_factor_on: boolean;
}

export const signInSecurityKey = ["sign-in-security"] as const;

export function getSignInSecurity() {
  return apiGet<SignInSecurity>("/access/sign-in-security/");
}

export function setSignInSecurity(two_factor_on: boolean, reason: string) {
  return apiSend<SignInSecurity>("PUT", "/access/sign-in-security/", { two_factor_on, reason });
}

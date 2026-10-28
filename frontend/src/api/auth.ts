import { apiGet, apiPost } from "./client";

export type Requirement = "password_change_required" | "two_factor_setup_required";

export interface CurrentUser {
  email: string;
  full_name: string;
  two_factor_enabled: boolean;
  two_factor_required: boolean;
  requirements: Requirement[];
}

export type Me =
  | { authenticated: true; user: CurrentUser }
  | { authenticated: false; two_factor_pending: boolean };

export type SignInResponse =
  | { status: "ok"; user: CurrentUser }
  | { status: "two_factor_required" };

export interface TwoFactorSetup {
  secret: string;
  otpauth_uri: string;
  qr_svg_data_uri: string;
}

export const meQueryKey = ["auth", "me"] as const;

export const getMe = () => apiGet<Me>("/auth/me/");

export const signIn = (email: string, password: string) =>
  apiPost<SignInResponse>("/auth/login/", { email, password });

export const verifyCode = (code: string) =>
  apiPost<SignInResponse>("/auth/login/verify/", { code });

export const signOut = () => apiPost<{ status: string }>("/auth/logout/");

export const startTwoFactorSetup = () => apiPost<TwoFactorSetup>("/auth/two-factor/setup/");

export const confirmTwoFactor = (code: string) =>
  apiPost<{ recovery_codes: string[] }>("/auth/two-factor/confirm/", { code });

export const changePassword = (current_password: string, new_password: string) =>
  apiPost<{ status: "ok"; user: CurrentUser }>("/auth/password/change/", {
    current_password,
    new_password,
  });

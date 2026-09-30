import type { CreateClientConfig } from "./generated/client.gen";

// Wired in via `runtimeConfigPath` (openapi-ts.config.ts), so the generated
// client is configured the moment it is imported.
export const createClientConfig: CreateClientConfig = (config) => ({
  ...config,
  baseUrl: "",
  credentials: "include",
});

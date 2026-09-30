import { describe, expect, it } from "vitest";

import { client } from "./generated/client.gen";

// Imports only the generated client: its config must not depend on some other
// module having been imported first.
describe("generated API client", () => {
  it("resolves API paths against the app's own origin", () => {
    expect(client.buildUrl({ url: "/api/v1/auth/login" })).toBe("/api/v1/auth/login");
  });

  it("sends the session cookie", () => {
    expect(client.getConfig().credentials).toBe("include");
  });
});

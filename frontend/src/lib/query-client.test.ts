import { describe, expect, it } from "vitest";

import { ApiError } from "@/api/errors";

import { createQueryClient } from "./query-client";

describe("createQueryClient retry policy", () => {
  const retry = createQueryClient().getDefaultOptions().queries?.retry as (
    failureCount: number,
    error: unknown,
  ) => boolean;

  it("does not retry client errors", () => {
    expect(retry(0, new ApiError(401))).toBe(false);
    expect(retry(0, new ApiError(404))).toBe(false);
  });

  it("retries server and network errors a bounded number of times", () => {
    expect(retry(0, new ApiError(503))).toBe(true);
    expect(retry(0, new ApiError(undefined))).toBe(true);
    expect(retry(3, new ApiError(503))).toBe(false);
  });
});

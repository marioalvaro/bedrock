import { describe, expect, it } from "vitest";

import { errorResult, networkErrorResult, okResult } from "@/test/responses";

import { ApiError, unwrap } from "./errors";

describe("unwrap", () => {
  it("returns the data of a 2xx response", async () => {
    expect(await unwrap(Promise.resolve(okResult({ a: 1 })))).toEqual({ a: 1 });
  });

  it("throws an ApiError carrying the status and the API's detail", async () => {
    const error = await unwrap(
      Promise.resolve(errorResult(409, { detail: "AAPL is already followed." })),
    ).catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 409, detail: "AAPL is already followed." });
  });

  it("has no detail when the error body does not carry a string one", async () => {
    const error = await unwrap(
      Promise.resolve(errorResult(422, { detail: [{ msg: "bad" }] })),
    ).catch((e: unknown) => e);

    expect(error).toMatchObject({ status: 422, detail: undefined });
  });

  it("throws an ApiError with no status when no response arrived", async () => {
    const error = await unwrap(Promise.resolve(networkErrorResult())).catch((e: unknown) => e);

    expect(error).toMatchObject({ status: undefined, detail: undefined });
  });
});

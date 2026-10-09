// A failed API call, carrying the HTTP status (undefined when no response arrived) and
// the API's `{"detail": "<reason>"}` text when it sent one.
export class ApiError extends Error {
  readonly status: number | undefined;
  readonly detail: string | undefined;

  constructor(status: number | undefined, detail?: string) {
    super(status === undefined ? "Network error" : `HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function detailOf(error: unknown): string | undefined {
  if (typeof error !== "object" || error === null || !("detail" in error)) return undefined;
  return typeof error.detail === "string" ? error.detail : undefined;
}

// The generated client returns failures instead of throwing; this turns a
// non-2xx (or missing) response into an ApiError so TanStack Query sees it.
export async function unwrap<T>(
  call: Promise<{ data?: T; error?: unknown; response?: Response }>,
): Promise<T> {
  const { data, error, response } = await call.catch(() => ({
    data: undefined,
    error: undefined,
    response: undefined,
  }));
  if (!response?.ok) {
    throw new ApiError(response?.status, detailOf(error));
  }
  return data as T;
}

export function isUnauthorized(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

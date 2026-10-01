// A failed API call, carrying the HTTP status (undefined when no response arrived).
export class ApiError extends Error {
  readonly status: number | undefined;

  constructor(status: number | undefined) {
    super(status === undefined ? "Network error" : `HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
  }
}

// The generated client returns failures instead of throwing; this turns a
// non-2xx (or missing) response into an ApiError so TanStack Query sees it.
export async function unwrap<T>(call: Promise<{ data?: T; response?: Response }>): Promise<T> {
  const { data, response } = await call.catch(() => ({ data: undefined, response: undefined }));
  if (!response?.ok) {
    throw new ApiError(response?.status);
  }
  return data as T;
}

export function isUnauthorized(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

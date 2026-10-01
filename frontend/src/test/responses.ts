// Shapes returned by the generated hey-api client (responseStyle "fields").
// Mocks use real `Response` objects so `ok`/`status` behave like the browser's.

export function okResult<T>(data: T, status = 200) {
  const body = status === 204 ? null : JSON.stringify(data);
  return { data, request: new Request("http://test/"), response: new Response(body, { status }) };
}

export function errorResult(status: number, error: unknown = { detail: "error" }) {
  return {
    data: undefined,
    error,
    request: new Request("http://test/"),
    response: new Response(JSON.stringify(error), { status }),
  };
}

// The client catches fetch rejections itself and returns them with no response.
export function networkErrorResult() {
  return {
    data: undefined,
    error: new TypeError("Failed to fetch"),
    request: new Request("http://test/"),
    response: undefined,
  };
}

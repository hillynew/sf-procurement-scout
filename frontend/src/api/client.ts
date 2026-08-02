const JSON_HEADERS = { "Content-Type": "application/json" };

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

async function handle<T>(resp: Response): Promise<T> {
  if (resp.status === 204) return undefined as T;
  const body = await resp.json().catch(() => null);
  if (!resp.ok) throw new ApiError(resp.status, body?.detail ?? resp.statusText);
  return body as T;
}

export const api = {
  get: <T>(path: string) => fetch(path).then((r) => handle<T>(r)),
  post: <T>(path: string, body?: unknown) =>
    fetch(path, {
      method: "POST",
      headers: JSON_HEADERS,
      body: body === undefined ? undefined : JSON.stringify(body),
    }).then((r) => handle<T>(r)),
  put: <T>(path: string, body: unknown) =>
    fetch(path, { method: "PUT", headers: JSON_HEADERS, body: JSON.stringify(body) }).then(
      (r) => handle<T>(r),
    ),
  del: <T>(path: string) => fetch(path, { method: "DELETE" }).then((r) => handle<T>(r)),
};

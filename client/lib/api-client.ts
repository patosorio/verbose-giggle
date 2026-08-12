export class ApiError extends Error {
  status: number;
  code: string;
  details: unknown;

  constructor(status: number, code: string, message: string, details: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

interface ApiFetchOptions {
  method?: string;
  body?: unknown;
  token?: string | null;
}

interface ErrorEnvelope {
  error?: {
    code?: string;
    message?: string;
    details?: unknown;
  };
}

export async function apiFetch<T>(path: string, opts: ApiFetchOptions = {}): Promise<T> {
  const { method = "GET", body, token } = opts;
  const url = `${process.env.NEXT_PUBLIC_API_BASE_URL}${path}`;

  const headers: Record<string, string> = {};
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(
      0,
      "network_error",
      "Unable to reach the server. Check your connection and try again."
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    if (!response.ok) {
      throw new ApiError(
        response.status,
        "network_error",
        "The server returned an unreadable response."
      );
    }
    return undefined as T;
  }

  if (!response.ok) {
    const envelope = payload as ErrorEnvelope;
    throw new ApiError(
      response.status,
      envelope.error?.code ?? "network_error",
      envelope.error?.message ?? "Something went wrong.",
      envelope.error?.details ?? null
    );
  }

  return payload as T;
}

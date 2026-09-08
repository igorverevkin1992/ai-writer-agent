// Клиент локального API. Изменяющие запросы несут X-Ugar-Panel (см. server.py).

/** Ошибка API: кроме текста несёт HTTP-статус и машинный код сервера
 *  (например 409 + «конфликт» при расхождении версии документа канона, аудит 5.2). */
export class ApiError extends Error {
  status: number;
  code?: string;
  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export function isConflict(e: unknown): boolean {
  return e instanceof ApiError && (e.status === 409 || e.code === "конфликт");
}

async function handle<T>(r: Response): Promise<T> {
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const d = data as { error?: string; code?: string };
    throw new ApiError(d.error || r.statusText, r.status, d.code);
  }
  return data as T;
}

export function apiGet<T>(url: string): Promise<T> {
  return fetch(url).then((r) => handle<T>(r));
}

export function apiPost<T>(url: string, body: unknown = {}): Promise<T> {
  return fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Ugar-Panel": "1" },
    body: JSON.stringify(body),
  }).then((r) => handle<T>(r));
}

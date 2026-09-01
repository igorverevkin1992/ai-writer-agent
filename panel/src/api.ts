// Клиент локального API. Изменяющие запросы несут X-Ugar-Panel (см. server.py).

async function handle<T>(r: Response): Promise<T> {
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((data as { error?: string }).error || r.statusText);
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

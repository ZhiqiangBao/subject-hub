async function parse(res: Response) {
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { detail: text };
  }
  if (!res.ok) {
    const detail = (data as { detail?: unknown })?.detail;
    const msg = typeof detail === "string" ? detail : Array.isArray(detail) ? "请求不对" : "没做成";
    throw new Error(msg);
  }
  return data;
}

export function api(path: string, init: RequestInit = {}) {
  return fetch(path, {
    credentials: "include",
    ...init,
    headers: {
      ...(init.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(init.headers || {}),
    },
  }).then(parse);
}

export const Auth = {
  me: () => api("/api/auth/me"),
  status: () => api("/api/auth/status") as Promise<{ admin_site: boolean }>,
  login: (username: string, password: string) =>
    api("/api/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }),
  register: (username: string, password: string, subjects: string[] = []) =>
    api("/api/auth/register", { method: "POST", body: JSON.stringify({ username, password, subjects }) }),
  logout: () => api("/api/auth/logout", { method: "POST" }),
};

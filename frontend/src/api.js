const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function request(path, options = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  return res.json();
}

export const api = {
  chat: (message, activeProjectId, awaiting, context, unlocked) =>
    request("/chat", {
      method: "POST",
      body: JSON.stringify({
        message,
        active_project_id: activeProjectId || null,
        awaiting: awaiting || null,
        context: context || null,
        unlocked: unlocked || false,
      }),
    }),
  listProjects: () => request("/projects"),
  systemStatus: () => request("/system"),
  deleteAllData: () => request("/data", { method: "DELETE" }),
};

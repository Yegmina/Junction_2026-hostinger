const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

export async function health() {
  const res = await fetch(`${API_BASE}/api/health`);
  return res.json();
}

export async function examples() {
  const res = await fetch(`${API_BASE}/api/examples`);
  return res.json();
}

// Streams server-sent events from POST /api/analyze and calls onEvent for each one.
export async function analyze(profile, onEvent, signal) {
  const res = await fetch(`${API_BASE}/api/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(profile),
    signal,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = Array.isArray(body.detail)
      ? body.detail.map((d) => `${d.loc?.slice(-1)[0]}: ${d.msg}`).join("; ")
      : body.detail;
    throw new Error(detail || `Request failed with status ${res.status}`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let cut;
    while ((cut = buffer.indexOf("\n\n")) >= 0) {
      const chunk = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      const data = chunk
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trim())
        .join("");
      if (data) onEvent(JSON.parse(data));
    }
  }
}

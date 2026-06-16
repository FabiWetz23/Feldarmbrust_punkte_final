export async function fetchJSON(url, opts = {}, apiKey = null, timeoutMs = 6000) {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeoutMs);

  const headers = { ...opts.headers };
  if (apiKey) {
    headers["X-API-KEY"] = apiKey;
  }

  try {
    const r = await fetch(url, { ...opts, headers, signal: controller.signal });
    const text = await r.text();
    const data = text ? JSON.parse(text) : null;
    if (!r.ok) {
      if (r.status === 401) throw new Error("Invalid API Key");
      const msg = (data && data.error) ? data.error : `HTTP ${r.status}`;
      throw new Error(msg);
    }
    return data;
  } finally {
    clearTimeout(id);
  }
}

export function api(base, path) {
  const b = (base || "").replace(/\/+$/, "");
  const p = path.startsWith("/") ? path : `/${path}`;
  return `${b}${p}`;
}

export function getState(base, apiKey) {
  return fetchJSON(api(base, "/state"), {}, apiKey);
}

export function upsertCompetitor(base, competitor, apiKey) {
  return fetchJSON(api(base, "/shooters"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(competitor)
  }, apiKey);
}

export function upsertSeries(base, series, apiKey) {
  return fetchJSON(api(base, "/series"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(series)
  }, apiKey);
}

export function setShot(base, seriesId, shot, apiKey) {
  return fetchJSON(api(base, `/series/${encodeURIComponent(seriesId)}/shot`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(shot)
  }, apiKey);
}

export function getKoState(base, apiKey) {
  return fetchJSON(api(base, "/ko/state"), {}, apiKey);
}

export function startKo(base, apiKey, pairs = null) {
  return fetchJSON(api(base, "/ko/start"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pairs })
  }, apiKey);
}

export function resetKo(base, apiKey) {
  return fetchJSON(api(base, "/ko/reset"), { method: "POST" }, apiKey);
}

export function setKoShot(base, matchId, shot, apiKey) {
  return fetchJSON(api(base, `/ko/matches/${encodeURIComponent(matchId)}/shot`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(shot)
  }, apiKey);
}

export function setKoWinner(base, matchId, slot, apiKey) {
  return fetchJSON(api(base, `/ko/matches/${encodeURIComponent(matchId)}/winner`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ slot })
  }, apiKey);
}

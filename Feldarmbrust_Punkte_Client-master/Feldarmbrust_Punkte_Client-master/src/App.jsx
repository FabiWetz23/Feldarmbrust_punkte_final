import React, { useEffect, useMemo, useRef, useState } from "react";
import Banner from "./components/Banner.jsx";
import CompetitorList from "./components/CompetitorList.jsx";
import RoundPicker from "./components/RoundPicker.jsx";
import ShotPad from "./components/ShotPad.jsx";
import { clearAll } from "./lib/offlineQueue.js";

import { loadSettings, saveSettings } from "./lib/storage.js";
import { uid } from "./lib/uuid.js";
import * as API from "./lib/api.js";
import { enqueue, flushQueue, peekAll } from "./lib/offlineQueue.js";
import { clampInt, getSeries, makeSeriesId, seriesTotal, competitorGrandTotal, normalizeShots, countInnerTens } from "./lib/math.js";


const SHOTS_PER_SERIES = 3;      // 3 shots per series
const KO_SHOTS_PER_END = 3;
const KO_MAX_ENDS = 5;
const MAX_ROUNDS = 10;           // 10 match rounds
const MIN_POINTS = 0;
const MAX_POINTS = 10;           // Max regular points (11 is inner ten)

export default function App() {
  const [tab, setTab] = useState("shoot");
  const [toolsOpen, setToolsOpen] = useState(false);
  const [competitorSelectOnly, setCompetitorSelectOnly] = useState(false);
  const [debugOpen, setDebugOpen] = useState(false);
  const [inputMode, setInputMode] = useState(() => localStorage.getItem("inputMode") || "normal");
  const [koState, setKoState] = useState(null);
  const [selectedKoCell, setSelectedKoCell] = useState(null);
  const [koPairSlots, setKoPairSlots] = useState([]);
  const [koAdminUnlocked, setKoAdminUnlocked] = useState(false);
  const [koRoundFilter, setKoRoundFilter] = useState(0);
  const [collapsedKoMatches, setCollapsedKoMatches] = useState({});
  const [settings, setSettings] = useState(loadSettings());
  const [darkMode, setDarkMode] = useState(() => loadSettings().darkMode ?? true);
  const [apiBase, setApiBase] = useState(() => {
    const saved = localStorage.getItem("apiBase") || "https://192.168.0.25:8000";
    return saved;
  });

  const [apiKey, setApiKey] = useState(() => {
    return localStorage.getItem("apiKey") || "1234";
  });

  const updateApiBase = (val) => {
    let url = val.trim();
    if (url && !url.startsWith("http")) {
      url = "https://" + url;
    }
    setApiBase(url);
    localStorage.setItem("apiBase", url);
  };

  const updateApiKey = (val) => {
    const trimmed = val.trim();
    setApiKey(trimmed);
    localStorage.setItem("apiKey", trimmed);
  };

  const updateDarkMode = (enabled) => {
    setDarkMode(enabled);
    setSettings(s => {
      const next = { ...s, darkMode: enabled };
      saveSettings(next);
      return next;
    });
  };

  const updateInputMode = (mode) => {
    setInputMode(mode);
    localStorage.setItem("inputMode", mode);
    if (mode !== "ko") setSelectedKoCell(null);
  };

  const toggleKoMatch = (matchId) => {
    setCollapsedKoMatches(prev => {
      const nextCollapsed = !prev[matchId];
      if (nextCollapsed && selectedKoCell?.matchId === matchId) {
        setSelectedKoCell(null);
      }
      return { ...prev, [matchId]: nextCollapsed };
    });
  };

  const [state, setState] = useState(null);

  const [online, setOnline] = useState(false);
  const [statusMsg, setStatusMsg] = useState("Not connected yet.");
  const [queueCount, setQueueCount] = useState(peekAll().length);

  const [activeCompetitorId, setActiveCompetitorId] = useState(null);
  // Default to Round 1 (Competition). Sighting are -1, 0.
  const [round, setRound] = useState(1);

  // add competitor form
  const [newName, setNewName] = useState("");
  const [newCountry, setNewCountry] = useState("");
  const [newStartNr, setNewStartNr] = useState("");

  const syncTimer = useRef(null);

  // --- OPTIMISTIC UI: mergedState ---
  const mergedState = useMemo(() => {
    const q = peekAll();
    if (!state && !q.length) return null;

    // Deep clone state to avoid mutations, or start with default structure
    const next = state
      ? JSON.parse(JSON.stringify(state))
      : { competition: { shooters: {}, series: {} } };

    if (!next.competition) next.competition = { shooters: {}, series: {} };
    if (!next.competition.shooters) next.competition.shooters = {};
    if (!next.competition.series) next.competition.series = {};

    if (!q.length) return next;

    for (const action of q) {
      if (action.type === "upsertCompetitor") {
        const c = action.payload;
        next.competition.shooters[c.id] = c;
      } else if (action.type === "upsertSeries") {
        const s = action.payload;
        // Don't overwrite if it already exists (it might have optimistic shots)
        if (!next.competition.series[s.id]) {
          next.competition.series[s.id] = { ...s, shot_scores: {} };
        }
      } else if (action.type === "setShot") {
        const { seriesId, shot } = action.payload;
        const ser = next.competition.series[seriesId];
        if (ser) {
          // If the server state has 'shots' as an array, we ensure we don't ignore it
          // normalizeShots prefers 'shots' array over 'shot_scores' dict.
          // To be safe, if 'shots' exists, we update it OR we force usage of shot_scores by deleting 'shots'
          if (Array.isArray(ser.shots)) {
            if (!ser.shot_scores) ser.shot_scores = {};
            ser.shots.forEach(s => {
              const idx = s.shot_number ?? s.index;
              const val = s.score ?? s.value;
              if (idx) ser.shot_scores[String(idx)] = val;
            });
            delete ser.shots;
          }

          if (!ser.shot_scores) ser.shot_scores = {};
          ser.shot_scores[String(shot.shot_number)] = shot.score;
        }
      }
    }
    return next;
  }, [state, queueCount]);

  const competitors = useMemo(() => {
    const dict = mergedState?.competition?.shooters;
    if (dict && typeof dict === "object") return Object.values(dict);
    // Fallback: aus leaderboard ziehen
    const lb = mergedState?.leaderboard;
    if (Array.isArray(lb)) return lb.map(x => x.shooter).filter(Boolean);
    return [];
  }, [mergedState]);


  const activeCompetitor = useMemo(
    () => competitors.find(s => s.id === activeCompetitorId) || null,
    [competitors, activeCompetitorId]
  );

  const activeSeries = useMemo(() => {
    if (!activeCompetitorId) return null;
    return getSeries(mergedState, activeCompetitorId, round);
  }, [mergedState, activeCompetitorId, round]);

  const seriesScore = useMemo(
    () => activeSeries ? seriesTotal(activeSeries, SHOTS_PER_SERIES) : 0,
    [activeSeries]
  );

  const grandScore = useMemo(
    () => activeCompetitorId ? competitorGrandTotal(mergedState, activeCompetitorId, SHOTS_PER_SERIES) : 0,
    [mergedState, activeCompetitorId]
  );

  const innerTensCountDeriv = useMemo(
    () => activeCompetitorId ? countInnerTens(mergedState, activeCompetitorId) : 0,
    [mergedState, activeCompetitorId]
  );

  async function connect() {
    const base = apiBase.trim();
    if (!base) {
      setStatusMsg("Please enter Server URL.");
      setOnline(false);
      return;
    }

    setStatusMsg("Connecting…");
    try {
      const st = await API.getState(base, apiKey);
      setState(st);
      setKoState(st?.ko || null);
      setOnline(true);
      setStatusMsg("Connected.");
      // set default active competitor
      const dict = st?.competition?.shooters;
      const list = dict ? Object.values(dict) : [];
      if (!activeCompetitorId && list.length) setActiveCompetitorId(list[0].id);
      setSettings(s => {
        const next = { ...s, apiBase: base };
        saveSettings(next);
        return next;
      });
    } catch (e) {
      setOnline(false);
      setStatusMsg(`Offline / No Connection: ${e.message}`);
    }
  }

  async function refreshState() {
    if (!apiBase.trim()) return;
    try {
      const st = await API.getState(apiBase.trim(), apiKey);
      setState(st);
      setKoState(st?.ko || null);
      setOnline(true);
      setStatusMsg("Connected.");
    } catch (e) {
      setOnline(false);
      setStatusMsg(`Offline: ${e.message}`);
    }
  }

  async function flush() {
    if (!apiBase.trim()) return { ok: false, flushed: 0, error: "no_server" };

    const res = await flushQueue(async (action) => {
      if (action.type === "upsertCompetitor") {
        await API.upsertCompetitor(apiBase.trim(), action.payload, apiKey);
      } else if (action.type === "upsertSeries") {
        await API.upsertSeries(apiBase.trim(), action.payload, apiKey);
      } else if (action.type === "setShot") {
        await API.setShot(apiBase.trim(), action.payload.seriesId, action.payload.shot, apiKey);
      } else {
        throw new Error("unknown_action");
      }
    });

    setQueueCount(peekAll().length);
    if (res.ok) {
      await refreshState();
    } else {
      setOnline(false);
      setStatusMsg(`Offline: ${res.error}`);
    }
    return res;
  }

  // Periodic auto-sync if online
  useEffect(() => {
    clearInterval(syncTimer.current);
    syncTimer.current = setInterval(async () => {
      if (!apiBase.trim()) return;
      // try flush first (handles coming back online)
      await flush();
    }, 3500);
    return () => clearInterval(syncTimer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiBase, apiKey]);

  useEffect(() => {
    if (!activeCompetitorId && competitors.length) {
      setActiveCompetitorId(competitors[0].id);
    }
  }, [competitors, activeCompetitorId]);

  useEffect(() => {
    if (koPairSlots.length || !competitors.length || koState?.active) return;
    setKoPairSlots(competitors.map(c => c.id));
  }, [competitors, koPairSlots.length, koState?.active]);

  useEffect(() => {
    const rounds = koState?.rounds || [];
    if (!rounds.length) {
      setKoRoundFilter(0);
      return;
    }
    if (koRoundFilter > rounds.length - 1) {
      setKoRoundFilter(rounds.length - 1);
    }
  }, [koState, koRoundFilter]);

  // initial connect attempt if saved
  useEffect(() => {
    if (apiBase) connect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = darkMode ? "dark" : "light";
  }, [darkMode]);

  async function createCompetitor() {
    const name = newName.trim();
    const country = newCountry.trim();
    const startNr = newStartNr.trim();

    if (!name) return;

    const competitor = {
      id: uid("sh"),
      name,
      country: country || null,
      start_number: startNr || null
    };

    try {
      await API.upsertCompetitor(apiBase.trim(), competitor, apiKey);
      await refreshState();
      setActiveCompetitorId(competitor.id);
      setNewName(""); setNewCountry(""); setNewStartNr("");
      openTab("shoot");
    } catch (e) {
      // offline → enqueue
      enqueue({ type: "upsertCompetitor", payload: competitor });
      setQueueCount(peekAll().length);
      setStatusMsg("Offline – Competitor queued.");

      // Optimistic update for UI state
      setActiveCompetitorId(competitor.id);
      setNewName(""); setNewCountry(""); setNewStartNr("");
      openTab("shoot");
    }
  }

  async function ensureSeriesExists(competitorId, r) {
    const id = makeSeriesId(competitorId, r);

    // 1. Check if it already exists in the server state
    if (getSeries(state, competitorId, r)) return id;

    // 2. Check if it's already in the merged state (optimistic)
    if (getSeries(mergedState, competitorId, r)) return id;

    // 3. Fallback check: is it already in the offline queue as an action?
    const queued = peekAll().find(a => a.type === "upsertSeries" && a.payload.id === id);
    if (queued) return id;

    // Server erwartet: round_number, shooter_id, shots_per_series
    const series = {
      id,
      shooter_id: competitorId,
      round_number: r,
      shots_per_series: SHOTS_PER_SERIES
    };

    try {
      await API.upsertSeries(apiBase.trim(), series, apiKey);
      await refreshState();
      return id;
    } catch (e) {
      enqueue({ type: "upsertSeries", payload: series });
      setQueueCount(peekAll().length);
      setStatusMsg("Offline – Series queued.");
      return id;
    }
  }


  async function writeShot(index, valueOrNull) {
    if (!activeCompetitorId) return;

    const seriesId = await ensureSeriesExists(activeCompetitorId, round);

    if (valueOrNull === null) {
      // "Löschen": wir setzen auf 0? oder lassen weg?
      // Am Server gibt's kein Delete-Endpunkt, darum: Setze 0 als "Korrektur".
      // Wenn du echtes Löschen willst: Server-Endpunkt ergänzen.
      valueOrNull = 0;
    }

    const v = clampInt(valueOrNull, MIN_POINTS, MAX_POINTS);
    if (v === null) {
      setStatusMsg(`Invalid: ${MIN_POINTS}–${MAX_POINTS}`);
      return;
    }

    const shot = { shot_number: index, score: v };
    try {
      await API.setShot(apiBase.trim(), seriesId, shot, apiKey);
      await refreshState();
    } catch (e) {
      enqueue({ type: "setShot", payload: { seriesId, shot } });
      setQueueCount(peekAll().length);
      setStatusMsg(`Shot queued: ${e.message}`);
    }
  }

  async function refreshKoState() {
    if (!apiBase.trim()) return;
    try {
      const ko = await API.getKoState(apiBase.trim(), apiKey);
      setKoState(ko);
      setOnline(true);
      setStatusMsg("Connected.");
    } catch (e) {
      setOnline(false);
      setStatusMsg(`KO offline: ${e.message}`);
    }
  }

  async function startKoMode() {
    if (!apiBase.trim()) return;
    try {
      const slots = koPairSlots.length ? koPairSlots : competitors.map(c => c.id);
      const pairs = [];
      for (let i = 0; i < slots.length; i += 2) {
        pairs.push([slots[i] || null, slots[i + 1] || null]);
      }
      const ko = await API.startKo(apiBase.trim(), apiKey, pairs);
      setKoState(ko);
      updateInputMode("ko");
      setSelectedKoCell(null);
      setStatusMsg("KO started.");
      await refreshState();
    } catch (e) {
      setStatusMsg(`KO start failed: ${e.message}`);
    }
  }

  async function resetKoMode() {
    if (!apiBase.trim()) return;
    try {
      const ko = await API.resetKo(apiBase.trim(), apiKey);
      setKoState(ko);
      setSelectedKoCell(null);
      setStatusMsg("KO reset.");
      await refreshState();
    } catch (e) {
      setStatusMsg(`KO reset failed: ${e.message}`);
    }
  }

  async function writeKoShot(valueOrNull) {
    if (!selectedKoCell) return;
    const score = valueOrNull === null ? null : clampInt(valueOrNull, MIN_POINTS, MAX_POINTS);
    if (score !== null && !Number.isInteger(score)) return;

    if (selectedKoValue !== null && !koAdminUnlocked) {
      const password = window.prompt("Admin password required to correct this shot.");
      if (password !== apiKey) {
        setStatusMsg("Correction blocked: wrong admin password.");
        return;
      }
      setKoAdminUnlocked(true);
    }

    try {
      const ko = await API.setKoShot(
        apiBase.trim(),
        selectedKoCell.matchId,
        {
          slot: selectedKoCell.slot,
          end_number: selectedKoCell.endNumber,
          shot_number: selectedKoCell.shotNumber,
          shoot_off: selectedKoCell.shootOff || false,
          score
        },
        apiKey
      );
      setKoState(ko);
      setStatusMsg("KO shot saved.");
    } catch (e) {
      setStatusMsg(`KO shot failed: ${e.message}`);
    }
  }

  async function setKoShootOffWinner(matchId, slot) {
    const password = window.prompt("Admin password required to choose shoot-off winner.");
    if (password !== apiKey) {
      setStatusMsg("Shoot-off decision blocked: wrong admin password.");
      return;
    }

    try {
      const ko = await API.setKoWinner(apiBase.trim(), matchId, slot, apiKey);
      setKoState(ko);
      setSelectedKoCell(null);
      setStatusMsg("Shoot-off winner saved.");
    } catch (e) {
      setStatusMsg(`Shoot-off winner failed: ${e.message}`);
    }
  }

  async function exportExcel() {
    if (!apiBase.trim()) return;
    try {
      const res = await fetch(API.api(apiBase.trim(), "/export"), {
        headers: { "X-API-KEY": apiKey },
      });
      if (!res.ok) {
        throw new Error(res.status === 401 ? "Invalid API Key" : `HTTP ${res.status}`);
      }

      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "feldarmbrust_export.xlsx";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setStatusMsg(`Export failed: ${e.message}`);
    }
  }

  const koPoints = (value) => {
    if (!Number.isInteger(value)) return 0;
    return value === 11 ? 10 : value;
  };

  const koShotLabel = (value) => {
    if (!Number.isInteger(value)) return "";
    return value === 11 ? "⑩" : String(value);
  };

  const koSlotTotal = (shots = []) => shots.reduce((sum, value) => sum + koPoints(value), 0);

  const selectedKoMatch = useMemo(() => {
    if (!selectedKoCell || !koState?.rounds) return null;
    for (const roundData of koState.rounds) {
      const match = (roundData.matches || []).find(m => m.id === selectedKoCell.matchId);
      if (match) return match;
    }
    return null;
  }, [koState, selectedKoCell]);

  const selectedKoValue = useMemo(() => {
    if (!selectedKoCell || !selectedKoMatch) return null;
    const value = selectedKoCell.shootOff
      ? selectedKoMatch.shoot_off?.[selectedKoCell.slot]
      : selectedKoMatch.ends?.[selectedKoCell.slot]?.[selectedKoCell.endNumber - 1]?.[selectedKoCell.shotNumber - 1];
    return Number.isInteger(value) ? value : null;
  }, [selectedKoCell, selectedKoMatch]);

  const visibleKoRounds = useMemo(() => {
    const rounds = koState?.rounds || [];
    if (!rounds.length) return [];
    return rounds.filter((_, index) => index === Number(koRoundFilter));
  }, [koState, koRoundFilter]);

  const isSecureApi = apiBase.trim().startsWith("https://");

  const connectionBanner = useMemo(() => {
    if (!apiBase.trim()) {
      return <Banner kind="warn" title="Server not set">Enter Server URL (Laptop IP + Port).</Banner>;
    }
    if (!isSecureApi) {
      return (
        <Banner kind="warn" title="Unencrypted connection">
          Use https:// for the server URL. HTTP can be intercepted or manipulated in WiFi.
        </Banner>
      );
    }
    if (online) {
      return (
        <Banner kind="ok" title="Online">
          Encrypted connection to <span style={{ fontWeight: 900 }}>{apiBase.trim()}</span>.
          {queueCount ? ` (${queueCount} actions pending)` : ""}
        </Banner>
      );
    }
    return (
      <Banner kind="bad" title="Offline / Unreachable">
        {statusMsg} {queueCount ? `(${queueCount} in queue)` : ""}
      </Banner>
    );
  }, [apiBase, isSecureApi, online, statusMsg, queueCount]);

  const openTab = (nextTab) => {
    if (nextTab !== "competitors") {
      setCompetitorSelectOnly(false);
    }
    setTab(nextTab);
    setToolsOpen(false);
  };

  const openCompetitorPicker = () => {
    setCompetitorSelectOnly(true);
    setTab("competitors");
    setToolsOpen(false);
  };

  const tabTitle = tab === "setup" ? "Setup" : tab === "competitors" ? (competitorSelectOnly ? "Select Competitor" : "Competitors") : "Input";

  return (
    <div className="container">
      <div className="header">
        <div>
          <div className="h1">Feldarmbrust Score</div>
          <div className="small">Touch-optimized • Offline-Queue</div>
        </div>

        <div className="row">
          <label className="themeSwitch">
            <input
              type="checkbox"
              checked={darkMode}
              onChange={(e) => updateDarkMode(e.target.checked)}
            />
            <span className="switchTrack" aria-hidden="true">
              <span className="switchThumb" />
            </span>
            <span className="small">Darkmode</span>
          </label>
          <span className="pill">Queue: <b style={{ color: "var(--text)" }}>{queueCount}</b></span>
          <button className="btn" onClick={() => refreshState()}>Refresh</button>
        </div>
      </div>

      {connectionBanner}

      <div className="card">
        <div className="toolHeader">
          <div>
            <div className="toolTitle">{tabTitle}</div>
            <div className="small">Scoring surface</div>
          </div>
          <button
            className="iconBtn"
            type="button"
            title="Setup and competitors"
            aria-label="Setup and competitors"
            onClick={() => setToolsOpen(open => !open)}
          >
            ⚙
          </button>
        </div>

        {toolsOpen && (
          <div className="adminMenu">
            <button className={`btn ${tab === "shoot" ? "primary" : ""}`} onClick={() => openTab("shoot")}>Input</button>
            <button className={`btn ${tab === "setup" ? "primary" : ""}`} onClick={() => openTab("setup")}>Setup</button>
            <button
              className={`btn ${tab === "competitors" && !competitorSelectOnly ? "primary" : ""}`}
              onClick={() => {
                setCompetitorSelectOnly(false);
                openTab("competitors");
              }}
            >
              Competitors
            </button>
          </div>
        )}

        {tab === "setup" && (
          <div className="grid2">
            <div>
              <div className="small" style={{ marginBottom: 6 }}>Server URL (Laptop)</div>
              <input
                className="input"
                placeholder="https://192.168.0.10:8000"
                value={apiBase}
                onChange={(e) => updateApiBase(e.target.value)}
              />
              <div style={{ height: 12 }} />
              <div className="small" style={{ marginBottom: 6 }}>API Key (Password)</div>
              <input
                className="input"
                type="password"
                placeholder="Password"
                value={apiKey}
                onChange={(e) => updateApiKey(e.target.value)}
              />
              <div style={{ height: 16 }} />
              <div className="row">
                <button className="btn primary" onClick={connect}>Connect</button>
                <button className="btn" onClick={async () => { await flush(); }}>Force Sync</button>
                <button
                  className="btn danger"
                  onClick={() => {
                    clearAll();
                    setQueueCount(0);
                    setStatusMsg("Queue cleared.");
                  }}
                >
                  Clear Queue
                </button>

                <button className="btn" onClick={exportExcel}>
                  Excel Export
                </button>
              </div>

              <div className="small" style={{ marginTop: 10 }}>
                Tip: Laptop and Tablet must be in the same WiFi. Use https:// plus the laptop IP.
              </div>
            </div>

            <div>
              <div className="small" style={{ marginBottom: 6 }}>Status</div>
              <div className="item">
                <div><b>Online:</b> {online ? "Yes" : "No"}</div>
                <div><b>Message:</b> {statusMsg}</div>
                <div><b>Competitors:</b> {competitors.length}</div>
                <div><b>Event:</b> {state?.eventId || "—"}</div>
              </div>
            </div>
          </div>
        )}

        {tab === "competitors" && (
          <div className={competitorSelectOnly ? "grid1" : "grid2"}>
            {!competitorSelectOnly && (
            <div>
              <div className="small" style={{ marginBottom: 6 }}>Add New Competitor</div>
              <div className="row">
                <input
                  className="input"
                  placeholder="No"
                  value={newStartNr}
                  onChange={(e) => setNewStartNr(e.target.value)}
                  style={{ width: "80px", marginRight: "8px" }}
                />
                <input
                  className="input"
                  placeholder="Name"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  style={{ flex: 1 }}
                />
              </div>

              <div style={{ height: 8 }} />
              <input
                className="input"
                placeholder="Country (optional)"
                value={newCountry}
                onChange={(e) => setNewCountry(e.target.value)}
              />
              <div style={{ height: 10 }} />
              <button className="btn primary" onClick={createCompetitor}>Add Competitor</button>

              <div className="small" style={{ marginTop: 10 }}>
                Offline? No problem: will be queued and synced later.
              </div>
            </div>
            )}

            <div>
              <div className="row" style={{ marginBottom: 10 }}>
                <span className="pill">{competitorSelectOnly ? "Select Competitor" : "Active"}</span>
                <b>{activeCompetitor ? `${activeCompetitor.name} (${activeCompetitor.country || "—"})` : "—"}</b>
                {competitorSelectOnly && (
                  <>
                    <div className="spacer" />
                    <button className="btn" onClick={() => openTab("shoot")}>Back</button>
                  </>
                )}
              </div>
              <CompetitorList
                competitors={competitors}
                activeId={activeCompetitorId}
                onSelect={(id) => {
                  setActiveCompetitorId(id);
                  setCompetitorSelectOnly(false);
                  openTab("shoot");
                }}
              />
            </div>
          </div>
        )}

        {tab === "shoot" && (
          <div>
            <div className="modeSwitch" style={{ marginBottom: 10 }}>
              <button
                className={`modeBtn ${inputMode === "normal" ? "active" : ""}`}
                onClick={() => updateInputMode("normal")}
              >
                Standard
              </button>
              <button
                className={`modeBtn ${inputMode === "ko" ? "active" : ""}`}
                onClick={() => {
                  updateInputMode("ko");
                  refreshKoState();
                }}
              >
                KO 5 Shots
              </button>
            </div>

            {inputMode === "normal" && (
              <>
            <div className="row" style={{ marginBottom: 10 }}>
              <span className="pill">Competitor</span>
              <b>{activeCompetitor ? `${activeCompetitor.name} (${activeCompetitor.country || "—"})` : "— select —"}</b>
              <div className="spacer" />
              <button className="btn" onClick={openCompetitorPicker}>Change</button>
            </div>

            <div className="row" style={{ marginBottom: 10 }}>
              <RoundPicker round={round} onRound={setRound} maxRounds={MAX_ROUNDS} />
              <div className="spacer" />
              <span className="pill">Series: <b style={{ color: "var(--text)" }}>{seriesScore}</b></span>
              <span className="pill">Inner Tens: <b style={{ color: "var(--text)" }}>{innerTensCountDeriv}</b></span>
              <span className="pill">Total: <b style={{ color: "var(--text)" }}>{grandScore}</b></span>
            </div>

            {!activeCompetitor && (
              <Banner kind="warn" title="No Competitor Active">
                Go to "Competitors" and select an active competitor.
              </Banner>
            )}

            {activeCompetitor && (
              <div className="shotGrid">
                {Array.from({ length: SHOTS_PER_SERIES }, (_, i) => i + 1).map(idx => {
                  const shots = normalizeShots(activeSeries);
                  const existing = shots.find(s => s.index === idx);
                  const currentValue = Number.isInteger(existing?.value) ? existing.value : null;


                  return (
                    <div key={idx} className="shotBox">
                      <div className="row" style={{ marginBottom: 6 }}>
                        <div className="shotIndex">Shot {idx}</div>
                        <div className="spacer" />
                        {Number.isInteger(currentValue) ? (
                          <span className="pill">Score: <b style={{ color: "var(--text)" }}>{currentValue === 11 ? "⑩" : currentValue}</b></span>
                        ) : (
                          <span className="pill">empty</span>
                        )}
                      </div>

                      <ShotPad
                        currentValue={Number.isInteger(currentValue) ? currentValue : null}
                        min={MIN_POINTS}
                        max={MAX_POINTS}
                        onSet={(v) => writeShot(idx, v)}
                        onClear={() => writeShot(idx, null)}
                      />
                    </div>
                  );
                })}
              </div>
            )}

            <div style={{ height: 12 }} />
            <div className="small">
              Note: ⌫ sets value to <b>0</b> (Server has no delete endpoint).
            </div>
              </>
            )}

            {inputMode === "ko" && (
              <div>
                <div className="row" style={{ marginBottom: 10 }}>
                  <span className="pill">KO Mode</span>
                  <b>{koState?.active ? "Active" : "Not started"}</b>
                  <div className="spacer" />
                  <button className="btn primary" onClick={startKoMode}>Start KO</button>
                  <button className="btn" onClick={refreshKoState}>Refresh</button>
                  <button className="btn danger" onClick={resetKoMode}>Reset KO</button>
                </div>

                {!koState?.active && (
                  <>
                    <Banner kind="warn" title="KO Not Started">
                      Choose who plays against whom, then press Start KO.
                    </Banner>
                    <div className="koPairList">
                      {Array.from({ length: Math.ceil(Math.max(competitors.length, 2) / 2) }, (_, pairIndex) => {
                        const leftIndex = pairIndex * 2;
                        const rightIndex = leftIndex + 1;
                        return (
                          <div className="koPairRow" key={pairIndex}>
                            <span className="pill">Match {pairIndex + 1}</span>
                            {[leftIndex, rightIndex].map(slotIndex => (
                              <select
                                className="select"
                                key={slotIndex}
                                value={koPairSlots[slotIndex] || ""}
                                onChange={(e) => {
                                  const next = [...koPairSlots];
                                  next[slotIndex] = e.target.value || null;
                                  setKoPairSlots(next);
                                }}
                              >
                                <option value="">Free</option>
                                {competitors.map(c => (
                                  <option key={c.id} value={c.id}>
                                    {(c.start_number || "-") + " " + c.name}
                                  </option>
                                ))}
                              </select>
                            ))}
                          </div>
                        );
                      })}
                    </div>
                  </>
                )}

                {koState?.active && (
                  <>
                    <div className="koRoundPicker">
                      <div className="small" style={{ marginBottom: 6 }}>Round</div>
                      <select
                        className="select"
                        value={koRoundFilter}
                        onChange={(e) => {
                          setKoRoundFilter(Number(e.target.value));
                          setSelectedKoCell(null);
                        }}
                      >
                        {(koState.rounds || []).map((roundData, index) => (
                          <option key={roundData.index} value={index}>
                            {roundData.name}
                          </option>
                        ))}
                      </select>
                    </div>

                    <div className="koBoard">
                      {visibleKoRounds.map(roundData => (
                        <div className="koRound" key={roundData.index}>
                          <div className="koRoundTitle">{roundData.name}</div>
                          {(roundData.matches || []).map(match => {
                            const isCollapsed = collapsedKoMatches[match.id];
                            const leftName = match.competitors?.[0]
                              ? `${match.competitors[0].start_number || "-"} ${match.competitors[0].name}`
                              : "Free";
                            const rightName = match.competitors?.[1]
                              ? `${match.competitors[1].start_number || "-"} ${match.competitors[1].name}`
                              : "Free";
                            return (
                            <div className={`koMatch ${isCollapsed ? "collapsed" : ""}`} key={match.id}>
                              <button className="koMatchHeader" type="button" onClick={() => toggleKoMatch(match.id)}>
                                <span className="koChevron">{isCollapsed ? ">" : "v"}</span>
                                <span className="koMatchTitle">Match {match.match_number}</span>
                                <span className="koMatchSummary">{leftName} vs {rightName}</span>
                                <span className="koMatchScore">{match.match_points?.[0] || 0}:{match.match_points?.[1] || 0}</span>
                              </button>
                              {!isCollapsed && (
                                <>
                              {[0, 1].map(slot => {
                                const competitor = match.competitors?.[slot];
                                const ends = match.ends?.[slot] || [];
                                const isWinner = match.winner_slot === slot;
                                return (
                                  <div className={`koCompetitor ${isWinner ? "winner" : ""}`} key={slot}>
                                    <div className="koCompetitorName">
                                      {competitor ? `${competitor.start_number || "-"} ${competitor.name}` : "Free"}
                                    </div>
                                    <div className="koEndStack">
                                      {Array.from({ length: koState.max_ends || KO_MAX_ENDS }, (_, endIndex) => (
                                        <div className="koEndRow" key={endIndex}>
                                          <span className="koEndLabel">E{endIndex + 1}</span>
                                          {Array.from({ length: koState.shots_per_end || KO_SHOTS_PER_END }, (_, shotIndex) => {
                                            const value = ends?.[endIndex]?.[shotIndex];
                                            const selected = selectedKoCell?.matchId === match.id
                                              && selectedKoCell?.slot === slot
                                              && selectedKoCell?.endNumber === endIndex + 1
                                              && selectedKoCell?.shotNumber === shotIndex + 1
                                              && !selectedKoCell?.shootOff;
                                            return (
                                              <button
                                                className={`koShotCell ${selected ? "selected" : ""}`}
                                                key={shotIndex}
                                                disabled={!competitor}
                                                onClick={() => {
                                                  if (!competitor) return;
                                                  setSelectedKoCell({
                                                    matchId: match.id,
                                                    slot,
                                                    endNumber: endIndex + 1,
                                                    shotNumber: shotIndex + 1,
                                                    shootOff: false,
                                                    competitorName: competitor.name
                                                  });
                                                }}
                                              >
                                                {koShotLabel(value)}
                                              </button>
                                            );
                                          })}
                                        </div>
                                      ))}
                                      {(match.needs_shoot_off || match.shoot_off?.some(v => Number.isInteger(v))) && (
                                        <div className="koEndRow">
                                          <span className="koEndLabel">SO</span>
                                          <button
                                            className={`koShotCell ${selectedKoCell?.matchId === match.id && selectedKoCell?.slot === slot && selectedKoCell?.shootOff ? "selected" : ""}`}
                                            disabled={!competitor}
                                            onClick={() => {
                                              if (!competitor) return;
                                              setSelectedKoCell({
                                                matchId: match.id,
                                                slot,
                                                endNumber: null,
                                                shotNumber: 1,
                                                shootOff: true,
                                                competitorName: competitor.name
                                              });
                                            }}
                                          >
                                            {koShotLabel(match.shoot_off?.[slot])}
                                          </button>
                                        </div>
                                      )}
                                    </div>
                                    <div className="koTotal">{match.match_points?.[slot] || 0}</div>
                                  </div>
                                );
                              })}
                              {match.needs_shoot_off
                                && match.winner_slot === null
                                && Number.isInteger(match.shoot_off?.[0])
                                && Number.isInteger(match.shoot_off?.[1])
                                && koPoints(match.shoot_off?.[0]) === koPoints(match.shoot_off?.[1]) && (
                                  <div className="koShootOffDecision">
                                    <div className="small">Shoot-off tie: choose closer to center</div>
                                    <div className="row">
                                      {[0, 1].map(slot => {
                                        const competitor = match.competitors?.[slot];
                                        if (!competitor) return null;
                                        return (
                                          <button
                                            className="btn primary"
                                            key={slot}
                                            onClick={() => setKoShootOffWinner(match.id, slot)}
                                          >
                                            {competitor.name}
                                          </button>
                                        );
                                      })}
                                    </div>
                                  </div>
                                )}
                                </>
                              )}
                            </div>
                          );
                          })}
                        </div>
                      ))}
                    </div>

                    {selectedKoCell && (
                      <div className="koEditor">
                        <div className="row" style={{ marginBottom: 8 }}>
                          <span className="pill">Editing</span>
                          <b>
                            {selectedKoCell.competitorName} - {selectedKoCell.shootOff
                              ? "Shoot-off"
                              : `End ${selectedKoCell.endNumber}, Shot ${selectedKoCell.shotNumber}`}
                          </b>
                          <div className="spacer" />
                          <button className="btn" onClick={() => setSelectedKoCell(null)}>Close</button>
                        </div>
                        <ShotPad
                          currentValue={selectedKoValue}
                          min={MIN_POINTS}
                          max={MAX_POINTS}
                          onSet={(v) => writeKoShot(v)}
                          onClear={() => writeKoShot(null)}
                        />
                      </div>
                    )}
                  </>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      <div style={{ height: 12 }} />
      <div className="card">
        <div className="row">
          <button className="btn" onClick={() => setDebugOpen(open => !open)}>
            {debugOpen ? "Hide Debug" : "Show Debug"}
          </button>
          <div className="spacer" />
          {debugOpen && (
            <button className="btn" onClick={() => navigator.clipboard?.writeText(JSON.stringify(state || {}, null, 2))}>
              Copy
            </button>
          )}
        </div>
        {debugOpen && (
          <pre style={{ margin: 0, marginTop: 10, whiteSpace: "pre-wrap" }}>
          {mergedState ? JSON.stringify(mergedState, null, 2) : "—"}
          </pre>
        )}
      </div>
    </div>
  );
}

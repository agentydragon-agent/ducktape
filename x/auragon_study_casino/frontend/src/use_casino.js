// Single React hook that exposes the casino's reactive state + mutation
// functions, swallowing the Y.Map/Y.Array iteration boilerplate. Lets
// study_casino.jsx swap its giant useState block for one line:
//
//     const casino = useCasino();
//     casino.credits / casino.tokens / casino.sessions / ...
//     casino.startSession("Biochem"); casino.redeem(prize); ...
//
// Non-economy document edits still sync through `/ws`. Balance-changing
// operations call server action endpoints, then apply the returned Y update.
//
// Active sessions live in the `sessions` Y.Map as entries with no
// `ended_at_ms` field.  `activeSession` is derived by finding the single
// sessions entry whose `ended_at_ms` is absent; `sessions` returns only
// completed entries.

import { casinoSync, Y } from "./sync.js";
import { useYArray, useYMap } from "./y_hooks.js";

export function useCasino() {
  const balance = useYMap(casinoSync.balance);
  const sessionsMap = useYMap(casinoSync.sessions);
  const prizesMap = useYMap(casinoSync.prizes);
  const prizeLogArr = useYArray(casinoSync.prizeLog);

  // Derived plain-JS views that downstream JSX expects unchanged. We round
  // the balance numbers because Yjs stores them as float64.
  //
  // These derivations are deliberately *not* memoized: a deep edit (e.g.,
  // editing a session's subject) does not change `sessionsMap`'s identity
  // or `.size`, and `useMemo([sessionsMap, sessionsMap.size, ...])` would
  // hand back a stale snapshot even though `observeDeep` correctly
  // re-rendered the component. The map iteration is cheap enough to do
  // every render.
  const credits = Math.floor(balance.get("credits") ?? 0);
  const tokens = Math.floor(balance.get("tokens") ?? 0);

  // Completed sessions only — those with ended_at_ms set.
  const sessions = [...sessionsMap.entries()]
    .filter(([, m]) => !!m.get("ended_at_ms"))
    .map(([id, m]) => ({
      id,
      subject: m.get("subject"),
      seconds: Math.floor(m.get("seconds") ?? 0),
      endedAt: Math.floor(m.get("ended_at_ms") ?? 0),
    }))
    .sort((a, b) => b.endedAt - a.endedAt);

  const prizes = [...prizesMap.entries()].map(([id, m]) => ({
    id,
    name: m.get("name"),
    cost: Math.floor(m.get("cost") ?? 0),
  }));

  const prizeLog = prizeLogArr
    .toArray()
    .map((m) => ({
      id: m.get("id"),
      name: m.get("name"),
      cost: Math.floor(m.get("cost") ?? 0),
      at: Math.floor(m.get("at_ms") ?? 0),
    }))
    .sort((a, b) => b.at - a.at);

  // In-progress session: the single sessions entry without ended_at_ms.
  const activeRaw = [...sessionsMap.entries()].find(([, m]) => !m.get("ended_at_ms"));
  const activeSession = activeRaw
    ? {
        id: activeRaw[0],
        subject: activeRaw[1].get("subject"),
        startTime: Math.floor(activeRaw[1].get("start_time_ms") ?? 0),
        paused: !!activeRaw[1].get("paused"),
        pausedDuration: Math.floor(activeRaw[1].get("paused_duration_ms") ?? 0),
        pauseStartedAt: activeRaw[1].get("pause_started_at_ms"),
      }
    : null;

  // === Mutations ===
  // Local-only session timing and prize catalog edits still use Y.Doc
  // transactions. Anything that changes credits, tokens, or prize_log goes
  // through `serverAction`.

  const startSession = (subject) => {
    if (activeSession) return; // one session at a time — illegal to start while one is running
    const id = `active-${Date.now()}`;
    casinoSync.mutate(() => {
      const sm = new Y.Map();
      casinoSync.sessions.set(id, sm);
      sm.set("subject", subject);
      sm.set("start_time_ms", Date.now());
      sm.set("paused", false);
      sm.set("paused_duration_ms", 0);
      sm.set("pause_started_at_ms", null);
    });
  };

  const pauseSession = () => {
    if (!activeSession || activeSession.paused) return;
    casinoSync.mutate(() => {
      const m = casinoSync.sessions.get(activeSession.id);
      if (!m) return;
      m.set("paused", true);
      m.set("pause_started_at_ms", Date.now());
    });
  };

  const resumeSession = () => {
    if (!activeSession || !activeSession.paused) return;
    const now = Date.now();
    const pausedFor = now - (activeSession.pauseStartedAt ?? now);
    casinoSync.mutate(() => {
      const m = casinoSync.sessions.get(activeSession.id);
      if (!m) return;
      m.set("paused", false);
      m.set("pause_started_at_ms", null);
      m.set("paused_duration_ms", activeSession.pausedDuration + Math.max(0, pausedFor));
    });
  };

  const newActionId = (prefix) =>
    typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? `${prefix}:${crypto.randomUUID()}`
      : `${prefix}:${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;

  const serverAction = async (path, prefix, payload = {}) => {
    const body = {
      ...payload,
      client_action_id: payload.client_action_id ?? newActionId(prefix),
      state_vector_b64: casinoSync.getStateVectorB64(),
    };
    const resp = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify(body),
    });
    if (!resp.ok) {
      let message = `${resp.status}`;
      try {
        const error = await resp.json();
        message = error?.detail?.message ?? error?.detail ?? message;
      } catch {
        // Keep the status-only message if the body is not JSON.
      }
      throw new Error(message);
    }
    return casinoSync.applyServerActionResponse(await resp.json());
  };

  const stopSession = () => {
    if (!activeSession) return;
    return serverAction("/actions/session/complete", "session.complete", {
      session_id: activeSession.id,
      ended_at_ms: Date.now(),
    });
  };

  const cancelSession = () => {
    if (!activeSession) return;
    casinoSync.mutate(() => casinoSync.sessions.delete(activeSession.id));
  };

  const editSession = (id, updates) => {
    const old = sessions.find((s) => s.id === id);
    if (!old) return;
    const newSec = typeof updates.seconds === "number" ? Math.max(0, updates.seconds) : old.seconds;
    const newSubject = updates.subject || old.subject;
    return serverAction("/actions/session/edit", "session.edit", {
      session_id: id,
      subject: newSubject,
      seconds: newSec,
    });
  };

  const deleteSession = (id) => {
    const old = sessions.find((s) => s.id === id);
    if (!old) return;
    return serverAction("/actions/session/delete", "session.delete", { session_id: id });
  };

  const addPastSession = (subject, seconds, endedAtMs) => {
    if (!subject || seconds <= 0) return;
    return serverAction("/actions/session/add-past", "session.add", {
      subject,
      seconds,
      ended_at_ms: endedAtMs,
    });
  };

  const redeemPrize = (prize) => {
    if (tokens < prize.cost) return;
    return serverAction("/actions/prize/redeem", "prize.redeem", { prize_id: prize.id });
  };

  const addPrize = (name, cost) => {
    if (!name || cost <= 0) return;
    const id = `p${Date.now()}`;
    casinoSync.mutate(() => {
      const m = new Y.Map();
      casinoSync.prizes.set(id, m);
      m.set("name", name);
      m.set("cost", cost);
    });
  };

  const deletePrize = (id) => {
    casinoSync.mutate(() => casinoSync.prizes.delete(id));
  };

  const convertToTokens = (amount) => {
    const n = Math.max(0, Math.floor(amount));
    if (n <= 0 || n > credits) return;
    return serverAction("/actions/convert", "convert", { amount: n });
  };

  const spinSlots = (wagerCredits) =>
    serverAction("/casino/slots/spin", "slots.spin", { wager_credits: Math.floor(wagerCredits) });

  const spinRoulette = ({ wagerCredits, betType, betNumber }) =>
    serverAction("/casino/roulette/spin", "roulette.spin", {
      wager_credits: Math.floor(wagerCredits),
      bet_type: betType,
      bet_number: betType === "number" ? betNumber : null,
    });

  const blackjackDeal = (wagerCredits) =>
    serverAction("/casino/blackjack/deal", "blackjack.deal", { wager_credits: Math.floor(wagerCredits) });

  const blackjackHit = (handId) => serverAction("/casino/blackjack/hit", "blackjack.hit", { hand_id: handId });

  const blackjackStand = (handId) => serverAction("/casino/blackjack/stand", "blackjack.stand", { hand_id: handId });

  const blackjackDouble = (handId) => serverAction("/casino/blackjack/double", "blackjack.double", { hand_id: handId });

  const exportData = () => {
    const data = {
      version: 3,
      exportedAt: new Date().toISOString(),
      credits,
      tokens,
      sessions,
      prizes,
      prizeLog,
      activeSession,
    };
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `study-casino-backup-${new Date().toISOString().slice(0, 10)}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const importData = (data) => {
    return serverAction("/actions/import", "data.import", { data });
  };

  const resetData = () => {
    return serverAction("/actions/reset", "data.reset");
  };

  return {
    credits,
    tokens,
    sessions,
    prizes,
    prizeLog,
    activeSession,
    startSession,
    pauseSession,
    resumeSession,
    stopSession,
    cancelSession,
    editSession,
    deleteSession,
    addPastSession,
    redeemPrize,
    addPrize,
    deletePrize,
    convertToTokens,
    spinSlots,
    spinRoulette,
    blackjackDeal,
    blackjackHit,
    blackjackStand,
    blackjackDouble,
    exportData,
    importData,
    resetData,
  };
}

function elapsedSeconds(session) {
  if (!session) return 0;
  const now = Date.now();
  let ms = now - session.startTime - (session.pausedDuration ?? 0);
  if (session.paused && session.pauseStartedAt) ms -= now - session.pauseStartedAt;
  return Math.max(0, ms / 1000);
}

# Study Casino Server-Side Resolution Plan

The current audit log is client-reported. It is useful for reconstructing what
the browser says happened, but it does not prove fairness because the browser
still draws random outcomes and mutates the Y.Doc balance.

Target shape:

1. Keep the Y.Doc for replicated user-facing state: sessions, balances, prizes,
   and prize redemptions.
2. Move wager settlement to authenticated backend endpoints. A request says
   "spin slots for 5 credits" or "bet 10 credits on red"; the server checks the
   canonical balance, draws the outcome, writes `game_events`, updates the
   canonical Y.Doc balance, and returns the outcome for animation.
3. Use server-side randomness with an explicit `rng_version` in each event. If
   we want user-auditable fairness later, add a commit/reveal seed chain or
   public daily server seed hash.
4. Convert games in risk order:
   - Slots first: one request, one response, no player decisions.
   - Roulette next: one request, one response, simple bet validation.
   - Blackjack last: needs a short-lived server hand state plus hit, stand,
     double, and settle actions.
5. Once a game is server-resolved, mark its events with
   `source = "server_resolved"` and stop accepting client-reported settle events
   for that game.

During migration, the client can still use the audit log endpoint for legacy
client-resolved games, but UI copy should distinguish client-reported history
from server-resolved history.

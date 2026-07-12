# Zerodha MCP — Frontend Design Audit & System

**Scope:** `src/ui/home.html`, `login.html`, `trade.html`, `positions.html` — 2,217 lines across 4 standalone, server-templated HTML files with inline CSS/JS. No build step, no framework, no shared stylesheet. Served by raw string substitution in `src/server.py` (`{tool_count}`, `{message}`, `{prefill_user_id}`, `{guest_btn}`).

Status: audit only. No code changes made or proposed to be made without separate approval per page/section.

---

## 1. Current UX Audit

### 1.1 What exists, page by page

| Page | Purpose | Visual language | Built by |
|---|---|---|---|
| `home.html` (834 lines) | MCP/API landing page — connect AI clients (claude.ai, Claude Code, Cursor, Postman), explain guest-vs-authenticated tool access, session status, changelog | Dark, "developer console" aesthetic — Inter + JetBrains Mono, grid background, glow, card grid | Original |
| `login.html` (472 lines) | Zerodha credential login → API key issuance → per-client setup guide | Same dark system as home | Original |
| `trade.html` (502 lines) | Place a BUY/SELL order, optionally with SL/Target/Trailing-SL | Light-first, `color-scheme: light dark`, mobile-card, iOS-form aesthetic | This session |
| `positions.html` (409 lines) | View open positions, live LTP/P&L via WebSocket, one-tap sell, modify SL/Target | Same light-first system as trade.html | This session (+ concurrent agent) |

**This is the core problem the rest of this document exists to fix: two unrelated design systems live in one product**, split exactly along the line of "who built it and when," not by any intentional distinction (e.g. "marketing pages are dark, app pages are light" — that would be a defensible rule, but it isn't stated or applied consistently; login.html is credential-entry, arguably the most trade.html-like task on the dark side).

### 1.2 Design tokens actually in use today

**System A — home.html / login.html:**
```
--bg: #09090b            --surface: #111116        --surface-2: #18181f
--border: rgba(255,255,255,.07)      --border-hover/2: rgba(255,255,255,.12-.13)
--text: #f4f4f5          --text-2: #a1a1aa         --text-3: #52525b
--accent: #4f8ef7        --accent-dim/ring: rgba(79,142,247,.12/.25)
--green: #22c55e         --green-dim/ring: rgba(34,197,94,.10/.22)
--amber: #f59e0b (home only)         --red: #f87171 (login only)
font: 'Inter' (400,500,600,700) + 'JetBrains Mono' (400,500), loaded from Google Fonts CDN
radius: 10 / 6 / 14 (home) — 10 / 14 (login, named --r/--r-lg, same values, different names)
```

**System B — trade.html / positions.html:**
```
--bg: #f4f5f8 (light) / #0e0f13 (dark)      --card: #ffffff / #191b22
--border: #e3e6eb / #2a2d38                 --text: #14161a / #eef0f4
--muted: #6b7280 / #9aa1af
--accent: #2d6cdf / #5b8dff                 --accent-ink: #ffffff / #0e0f13
--buy: #0a8f4f / #35d17e   --buy-bg: #e7f8ee / #10281c
--sell: #d1392a / #ff6b5e  --sell-bg: #fdecea / #2c1512
font: system-ui stack (-apple-system, "Segoe UI", ...) — no webfont, no mono font at all
radius: 14 (single token, --radius)
```

No shared file, no CSS custom-property bridge, no shared component. Every page redefines `.card`, `.btn`/`.primary`, `.msg`, spinner/loading states, and copy-to-clipboard logic independently. Confirmed by direct read: `login.html`'s `.submit-btn` and `trade.html`'s `.primary` are the same visual button, hand-duplicated with different class names, different property order, and (as shown above) different color values for a semantically identical "primary accent" role.

### 1.3 Verified functional inventory (what each page actually does, read from the live code)

**`home.html`**
- Hero + status pills (`{tool_count}` server-injected)
- Guest/authenticated split explainer, two-card grid
- SSE endpoint display + copy button
- Tabbed quick-start guide (claude.ai / Claude Code / Claude Desktop / Cursor / Postman) — 5 tabs, `showTab()`, plain show/hide, no transition
- Security row (3-up static text)
- Live session-status card — `fetch('/auth/status')`, three states (authenticated / browser-session / none), each with different button set
- "Trading web app" section — 2 cards linking to `/trade` and `/positions` (added this session)
- "What's new" changelog — 5 static entries, one tagged `NEW` (added this session, never revisited/pruned since)
- Server info + supported-clients grid (static reference content)
- Footer facts row

**`login.html`**
- Credential form (Client ID, Password, TOTP) → POST `/login`
- Server-injected `{message}` alert block (success or error) — the *entire* subsequent DOM is decided by whether `.alert.ok` exists (`if (!document.querySelector('.alert.ok')) return;`), a fragile coupling between server-rendered HTML and client-side JS control flow
- On success: API key reveal (blur-until-click), copy button, 5-tab setup guide (same client set as home.html's quick-start, duplicated markup and duplicated tab-switch JS — `showGuideTab()` vs `showTab()`, same logic, different function name)
- "Continue as guest" link (`{guest_btn}`, conditionally injected server-side)

**`trade.html`**
- Top-nav (Trade/Positions) — added this session, present only on trade.html + positions.html, absent from home.html/login.html
- PIN field (no server-side session — every request re-sends the PIN)
- Symbol search: debounced (200ms) autocomplete, abortable in-flight fetch, keyboard nav (↑↓/Enter/Esc), lot-size-aware quantity hint
- BUY/SELL toggle, order-type (MARKET/LIMIT) toggle revealing a conditional limit-price field
- Product/Exchange selects
- Collapsible "Add SL/Target" section (SL trigger+limit, Target trigger+limit, Trailing SL points) — added this session
- Query-param prefill (`?symbol=&exchange=&security_id=&segment=`) from a positions.html deep link — sets SELL side and auto-expands the SL/Target section
- Two-screen flow: form → preview (server round-trip to `/trade/preview`) → confirm → place (`/trade/place`)
- Post-success: inline "View in positions →" link

**`positions.html`**
- Top-nav (shared markup, not shared file, with trade.html)
- PIN field, auto-connects once 4+ characters are typed (`oninput`) *or* on Enter — two independent code paths for the same action, confirmed source of a real production bug this session (a template-literal escaping error broke the entire script block; see §1.4)
- Summary row: open-position count + total P&L (client-computed, re-derived on every tick)
- Position cards: symbol/exchange/kind tags, qty @ avg, 3-up metric grid (LTP/P&L/Qty), SL/Target/Trailing badges, 3 actions (Sell, Modify, "…" deep-link to trade.html)
- Live WebSocket (`/ws/prices`) — snapshot-then-tick protocol, auto-reconnect with exponential backoff (1s → 15s cap), per-tick DOM patch + 300ms "flash" highlight on the touched card
- Modify modal — bottom-sheet pattern (only bottom-sheet in the whole product; every other overlay-like state in the system is a full-screen swap, e.g. trade.html's confirm card)
- Sell — one-tap with PIN as the sole confirmation (explicit product decision, not an oversight)

### 1.4 Confirmed defects (not opinions — verified against source/runtime)

1. **Two incompatible design systems in one product**, as above — the single largest structural issue.
2. **Zero code sharing between pages.** Every shared concept (card, button, alert/msg banner, copy-to-clipboard, tab switcher) is manually re-implemented per file, already 2× (soon 4×) duplicated logic for identical UI concepts.
3. **A template-literal syntax error in `positions.html` shipped to production and broke the entire page** (`\\"` inside a nested ternary inside a backtick literal — a `SyntaxError` that silently killed every function in the `<script>` block, including the PIN auto-connect handler). Root cause: no build step means no linter/bundler ever parses this JS before it reaches a browser. This is a structural risk, not a one-off mistake — the same class of failure can recur silently on any future edit.
4. **No shared navigation.** `home.html` and `login.html` have no way to reach `/trade` or `/positions` except a link buried in a content section; `trade.html`/`positions.html` have a 2-item nav that doesn't link back to `/` or `/login`. There is no single, consistent "where am I in this product" mental model.
5. **PIN is re-entered per page load, per tab, with no persistence** (not localStorage, not sessionStorage, not a cookie) — by design, presumably for security, but never stated as such anywhere in the UI; reads as a rough edge rather than an intentional constraint to the person typing a 4-digit PIN on every visit.
6. **Auto-connect race pattern**: `positions.html`'s PIN field has both `onkeyup` (Enter-only) and `oninput` (length-based) handlers independently calling `load()`, with a manual `pinAutoLoaded` boolean guarding re-entry — a hand-rolled debounce/guard where a single `input` listener with a length check would do, half the code, no dual-path confusion.
7. **`positions.html`'s live P&L math is duplicated client-side** (`(ltp - avg) * qty`) separately from whatever the server's `get_positions_for_web()` computes server-side — two independent P&L formulas that must be kept in sync by hand across a network boundary; a future server-side fee/charge adjustment would silently diverge from the client's live-tick recompute.
8. **No loading skeletons anywhere.** Every async boundary (symbol search, positions fetch, order placement, modify) shows either nothing or a text-swap on the triggering button — no perceived-performance treatment for the actual data area (positions list, summary row, confirm card).
9. **No error boundary / retry affordance beyond the WebSocket's own reconnect.** A failed `/positions/data` fetch shows a text message in `#pinMsg` with no retry button — user must manually re-submit the PIN field to retry.
10. **Accessibility gaps, consistent across all 4 pages**: no visible focus outline beyond browser default on non-input elements (buttons/links rely entirely on `:active`/`:hover`, nothing for keyboard-only nav on buttons), no `aria-live` region for the WebSocket connection-status text or tick updates (a screen reader gets zero notice that a price/P&L changed), color is the *only* signal for buy/sell/pos/neg (no icon, no text-only fallback), modal backdrop (`positions.html`) has no focus trap and no Escape-to-close.
11. **Inconsistent copy-to-clipboard implementations**: `home.html` has 2 (`copyEndpoint`, `copyGuestToken`), `login.html` has 2 more (`copyKey`, `copyCode`) — 4 near-identical functions, no shared helper, each with its own "Copied!" timeout literal (2000ms, consistent by coincidence not by reuse).
12. **The "What's new" section on `home.html` is a static, manually-maintained list with no date, no versioning, and a `NEW` badge on exactly one entry** — it will silently go stale (every future feature either doesn't get added, or the badge logic never moves) with nothing enforcing upkeep.

---

## 2. Problems (synthesized from §1, ranked by user-facing impact)

| # | Problem | Impact | Evidence |
|---|---|---|---|
| P1 | Two design systems, no bridge | Product feels like 2 different apps stitched together; every new page is a coin-flip on which system to extend | §1.1, §1.2 |
| P2 | No shared component layer | Every fix/tweak must be hand-applied 2-4× (already missed once — SL/Target styling differs subtly between `trade.html`'s inline section and `positions.html`'s badges for the *same data*) | §1.3, §1.4.2 |
| P3 | No build/lint step for JS embedded in HTML | A silent syntax error can ship and break a whole page with zero warning, as already happened | §1.4.3 |
| P4 | No cross-page navigation model | Users (and future me) have no way to reason about "the site" as a whole, only "the page I'm currently looking at" | §1.4.4 |
| P5 | Client/server logic duplication (P&L, tab-switching, copy-to-clipboard) | Correctness risk (P&L can silently diverge) + maintenance tax | §1.4.7, §1.4.11 |
| P6 | No accessibility baseline | Excludes keyboard/screen-reader users entirely from the trading flows — the highest-stakes pages in the product | §1.4.10 |
| P7 | No perceived-performance treatment | Every async action feels like "did I click it?" uncertainty, especially on a live-money trading form | §1.4.8 |
| P8 | Changelog/"what's new" is unmaintainable as designed | Will misrepresent the product's actual current state within a few feature cycles | §1.4.12 |

---

## 3. Opportunities

1. **One design system, two densities.** The dark "console" aesthetic (home/login) and the light "mobile app" aesthetic (trade/positions) don't need to merge into one look — but they need one *token vocabulary* so a button, card, or alert means the same thing everywhere, themed via the same `prefers-color-scheme`/`data-theme` mechanism `trade.html`/`positions.html` already use correctly (and `home.html`/`login.html` don't use at all — they're dark-only, no light variant, no `color-scheme` declaration).
2. **A tiny shared partial, not a framework.** Given "no build step" is either a hard constraint or at least the status quo, the pragmatic move is a single `_shared.css`/`_shared.js` (or an inlined `<!--#include-->`-style server-side concat at template-load time, matching how `_HOME_TEMPLATE`/`_TRADE_TEMPLATE`/etc. are already loaded as raw strings in `server.py`) covering: CSS tokens, `.card`/`.btn`/`.msg`/`.badge` primitives, `copyToClipboard(text, btnEl)`, `showTab(containerId, id, btn)`. This closes P2, P5 without introducing React/build tooling this project has never used.
3. **A real top-level nav, present on all 4 pages.** Even a simple 4-item bar (Home · Trade · Positions · Login/Session) turns "four separate tools" into "one product with four views."
4. **Skeleton/shimmer states for the 3-4 async boundaries that matter** (positions list, symbol search results, order placement, modify) — cheap, high perceived-quality win.
5. **A minimal a11y pass**: visible `:focus-visible` rings using the existing accent color (already defined, just never applied to `:focus-visible`), `aria-live="polite"` on the WS connection-status and tick-updated regions, non-color signal (▲/▼ glyph, already used nowhere despite being the single most standard trading-UI convention) alongside buy/sell green/red.
6. **Turn the changelog into a generated artifact** — even something as simple as reading the last N conventional-commit-style messages touching `src/ui/`/`src/execution/`/`src/brokers/streaming.py` at template-render time beats hand-maintained prose that nobody remembers to update.
7. **Since PIN-per-load is a deliberate security stance**, say so in the UI once (a small `title`/tooltip on the PIN field: "Not stored — re-enter each visit"), turning a rough edge into a legible decision.

---

## 4. Design System (proposed — not implemented)

### 4.1 Principle

**One token vocabulary, two densities, shared primitives.** Dark "console" density for informational/setup pages (home, login); light-first "app" density for transactional pages (trade, positions) — both pulling from the same named tokens so a design change to `--accent` or `--radius-md` propagates everywhere, and so a future 5th page never has to choose a system from scratch.

### 4.2 Unified token set (superset resolving A vs B naming collisions)

```css
:root {
  color-scheme: light dark;

  /* Surface */
  --bg:            #f4f5f8;   --surface:   #ffffff;   --surface-2: #f4f5f8;
  --border:        #e3e6eb;   --border-hover: #c7cdd6;
  --text:          #14161a;   --text-2:    #6b7280;   --text-3: #9aa1af;

  /* Brand */
  --accent:        #2d6cdf;   --accent-dim: rgba(45,108,223,.10); --accent-ring: rgba(45,108,223,.25);
  --accent-ink:    #ffffff;

  /* Semantic */
  --buy:  #0a8f4f;  --buy-dim:  #e7f8ee;  --buy-ring:  rgba(10,143,79,.22);
  --sell: #d1392a;  --sell-dim: #fdecea;  --sell-ring: rgba(209,57,42,.22);
  --amber:#b45309;  --amber-dim:#fff4e0;  --amber-ring:rgba(180,83,9,.22);

  /* Type */
  --font-ui:   'Inter', -apple-system, "Segoe UI", system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', 'Fira Code', monospace;

  /* Shape */
  --radius-sm: 6px; --radius-md: 10px; --radius-lg: 14px;
  --shadow-sm: 0 1px 2px rgba(16,24,40,.04), 0 1px 3px rgba(16,24,40,.06);
  --shadow-lg: 0 12px 40px rgba(0,0,0,.14);
}
:root[data-density="console"] {
  --bg: #09090b; --surface: #111116; --surface-2: #18181f;
  --border: rgba(255,255,255,.07); --border-hover: rgba(255,255,255,.13);
  --text: #f4f4f5; --text-2: #a1a1aa; --text-3: #52525b;
  --accent: #4f8ef7; --accent-dim: rgba(79,142,247,.12); --accent-ring: rgba(79,142,247,.25);
  --accent-ink: #0e0f13;
  --shadow-lg: 0 24px 64px rgba(0,0,0,.6);
}
@media (prefers-color-scheme: dark) {
  :root:not([data-density="console"]) {
    --bg: #0e0f13; --surface: #191b22; --surface-2: #18181f;
    --border: #2a2d38; --border-hover: #3a3d48;
    --text: #eef0f4; --text-2: #9aa1af; --text-3: #6b7280;
    --accent: #5b8dff; --accent-ink: #0e0f13;
    --buy: #35d17e; --buy-dim: #10281c;
    --sell: #ff6b5e; --sell-dim: #2c1512;
  }
}
```

`data-density="console"` is set on `<html>` server-side for `home.html`/`login.html` only — a single attribute, not a class war, and it composes with the existing OS-level dark-mode media query for `trade.html`/`positions.html`'s light-default/dark-capable pages, rather than fighting it.

### 4.3 Component inventory (shared primitives to extract)

| Component | Currently duplicated in | Target file |
|---|---|---|
| `.card` | all 4 pages, 4 slightly different implementations | `_shared.css` |
| `.btn` / `.btn-primary` / `.btn-ghost` / `.btn-sm` | home (4 variants), login (`.submit-btn`, `.done-btn`, `.guest-btn`), trade (`.primary`, `.secondary`, `.side button`), positions (`.btn`, `.btn.sell`, `.btn.modify`) — **11 near-identical button variants across 4 files** | `_shared.css`, collapsed to `.btn` + 4 modifier classes (`primary`/`ghost`/`sell`/`buy`) |
| `.msg` / `.alert` (success/error banner) | home has none (uses `alert()`/inline text), login has `.alert.ok/.err`, trade/positions have `.msg.ok/.err` — same concept, 2 different class names | `_shared.css`, one name (`.banner`) |
| Copy-to-clipboard button + feedback | 4 independent JS functions | `_shared.js` → `copyToClipboard(text, btnEl, labelDefault, labelOk)` |
| Tab switcher | home (`showTab`), login (`showGuideTab`) — identical logic | `_shared.js` → `switchTab(groupSelector, targetId, btnEl)` |
| Top nav | trade/positions only, hand-copied markup | `_shared.html` fragment, injected server-side, extended to all 4 pages |
| Badge (pill/tag) | home `.pill`/`.badge`/`.no-login-tag`/`.oauth-tag`, positions `.pos-tag`/`.sl-badge`/`.tgt-badge`/`.trail-badge` — 8 variants of "small rounded label" | `_shared.css` → `.badge` + color modifier |
| Spinner | login only today; trade/positions button-disable-with-text-swap is a *worse* pattern for the same need | `_shared.css` → one `.spinner`, used everywhere an async action is in flight |
| Empty state | positions only (`.empty`) | `_shared.css`, reused for e.g. an empty symbol-search result, empty order history |
| Skeleton/shimmer | none exist | new, `_shared.css` |

### 4.4 Typography

| Role | Font | Size | Weight | Current inconsistency |
|---|---|---|---|---|
| Page title (h1) | Inter | console: 36px / app: 20px | 700 | trade.html's h1 (1.25rem) and login.html's h1 (20px) are the same visual size via different units (`rem` vs `px`) — pick one unit system |
| Section head | Inter | 11px | 600, uppercase, .08em tracking | Consistent already — good, keep |
| Body | Inter | 13-14px | 400-500 | Consistent |
| Numeric/data (prices, IDs, code) | JetBrains Mono | 12-13px | 400-500 | **Missing entirely from trade.html/positions.html** — prices are rendered in the UI font; a live-trading page displaying money should use tabular/mono figures for scannability and to prevent digit-jitter on tick updates (positions.html already sets `font-variant-numeric: tabular-nums` on `.pos-metric-val` — correct instinct, but system-ui isn't a true monospace, so digits still aren't perfectly aligned; adding `--font-mono` to that one rule captures the actual intent) |
| Micro-label (uppercase eyebrow) | Inter | 11-12px | 700, .04-.08em tracking | Consistent |

**Load strategy**: both fonts already load once via Google Fonts CDN on home/login; extending that `<link>` to trade/positions costs one more render-blocking request per page — acceptable given these are server-rendered, cache-friendly static templates, not something optimizing for a payload budget today.

### 4.5 Responsive strategy

Current state: `home.html`/`login.html` have exactly one breakpoint (`max-width: 620px`, home only — login has none at all, relying on its `max-width: 440px` card + `padding: 24px` on body to degrade acceptably). `trade.html`/`positions.html` have zero explicit breakpoints; they're single-column, `max-width: 460-520px`, centered — effectively "mobile-first, and also fine on desktop because it never grows past mobile width."

**Proposed strategy**: keep the *content* mobile-first (this is genuinely a mobile-use-case product — placing/checking orders from a phone), but give desktop viewports something better than "a phone-width column floating in the middle of a wide screen":
- `home.html`/`login.html`: keep current behavior, already reasonable for their content type (a landing page and a login form both read fine centered).
- `trade.html`/`positions.html`: at `min-width: 640px`, allow the positions list to become a 2-column card grid (not a data table — the card format has real value for at-a-glance SL/Target badges) and let the trade form sit alongside a live preview panel instead of a full-screen swap between form and confirm — this is the single highest-value *layout* change available, since today's confirm-card full-screen-swap loses your place in a way that's jarring on a screen with room to show both.
- One shared breakpoint scale across all 4 files: `480px` (phone→large-phone), `640px` (tablet-portrait, positions grid kicks in), `960px` (trade side-by-side kicks in). Currently zero of these three exist as a shared constant anywhere.

### 4.6 Animation guidelines

Current state (audited, all real, all reasonable in isolation): fade-up entrance (`up` keyframe, home/login, staggered `.a1`-`.a6` classes), blinking status dot (`blink`, home), spinner (`spin`, login), pop-in success icon (`pop`, login), pulsing connection dot (`pulse`, positions), 300ms border-flash on tick (positions), scale-down on `:active` (buttons, trade/positions only — home/login buttons have no press feedback at all).

**Proposed guidelines going forward:**
- **Motion communicates state change, never decoration.** Every current animation already satisfies this — keep the bar there.
- **Duration bands**: micro-feedback (press, hover) 100-150ms; state transitions (tab switch, card expand, modal open) 200-300ms; entrance/attention (page load stagger, new-data flash) 300-450ms. Today's values already cluster correctly here — codify as tokens (`--dur-micro: 120ms`, `--dur-transition: 250ms`, `--dur-entrance: 400ms`) instead of the current 6+ hand-picked literals (`.12s`, `.15s`, `.2s`, `.3s`, `.35s`, `.45s`) scattered per file.
- **Respect `prefers-reduced-motion`** — audited: **zero** of the current 4 files check this media query. Every keyframe animation (fade-up, blink, pulse, pop, flash) should collapse to an instant state change under `prefers-reduced-motion: reduce`. This is a real, currently-unmet accessibility gap (ties to P6).
- **Extend press-feedback (`:active { scale(.97-.98) }`) to every clickable element**, including home/login's buttons and links, for tactile consistency.

### 4.7 New page layouts (proposed structure, not visual mockups — for approval before any mockup/implementation work)

**Home (`/`)** — restructure into: Hero → primary nav (new) → "Trading" quick-access (2 cards, exists, keep) → "Connect an AI client" (exists, keep, becomes secondary content below the fold rather than the dominant middle section it is today) → session status → changelog (regenerated, not hand-written) → footer. Net effect: end-users who came to trade see trading first; developers connecting an MCP client still find full setup docs, just not gating everything above it.

**Login (`/login`)** — unchanged structural flow (form → success → guide), restyled onto the unified token set, spinner/button patterns shared with trade/positions instead of reimplemented.

**Trade (`/trade`)** — mobile: unchanged single-column flow. `≥960px`: two-column — form on the left, a live-updating summary panel on the right that mirrors what's currently the separate "confirm" screen, updating in place as fields change, with the actual PLACE action staying as an explicit, separate, deliberate tap (never auto-submit) — this keeps every existing safety property (confirm-before-place) while removing the jarring full-screen swap on larger viewports.

**Positions (`/positions`)** — mobile: unchanged single-column card list. `≥640px`: 2-column card grid. Summary row becomes sticky at top on scroll (currently scrolls away, so P&L is invisible once you're scrolled into a long position list — confirmed by reading the layout, `.summary-row` has no `position: sticky`).

**New: a shared top nav**, present on all 4 pages, 4 items (Home / Trade / Positions / Session), current-page indicated the same way `trade.html`/`positions.html` already indicate it (`.on` class, accent border+bg) — extending an existing, working pattern rather than inventing a new one.

---

## 5. Implementation Plan (sequenced, no step taken without separate go-ahead)

This is a plan to review, not a commitment to execute — nothing below happens until you approve, and even after approval each phase should land as its own reviewable change, not one giant rewrite.

| Phase | Scope | Risk | Depends on |
|---|---|---|---|
| 0 | Land `DESIGN.md` (this file) as the reference doc; no code touched | None | — |
| 1 | Extract `_shared.css` (tokens + `.card`/`.btn`/`.badge`/`.banner`/spinner primitives) and `_shared.js` (`copyToClipboard`, `switchTab`) as new files under `src/ui/`; wire into `server.py`'s existing template-loading (`open(...).read()`) via simple string concatenation at load time — no new dependency, no build step introduced | Low — additive files, existing pages keep working until each is migrated to consume them | Phase 0 |
| 2 | Migrate `trade.html` + `positions.html` onto `_shared.css`/`_shared.js`, replacing their local duplicate CSS/JS 1:1 (visual output unchanged, verified by manual before/after screenshot diff) | Medium — touches the two live-money pages; needs the same manual-browser-test discipline as any trade.html/positions.html change this session already followed | Phase 1 |
| 3 | Migrate `home.html` + `login.html` onto the same shared files, applying `data-density="console"` | Medium — touches the OAuth/login critical path; needs careful testing of the `{message}`/`.alert.ok` JS-DOM coupling called out in §1.4.3-adjacent finding | Phase 1 |
| 4 | Add shared top nav to all 4 pages | Low, cosmetic + link-only | Phase 1 (uses shared badge/link styles) |
| 5 | Accessibility pass: `:focus-visible` rings, `aria-live` regions, `prefers-reduced-motion` guards, non-color buy/sell signal | Low, additive-only | Phase 1-4 (styles must exist first) |
| 6 | Responsive layout upgrades (positions 2-col grid, trade side-by-side, sticky summary) | Medium — genuine layout restructuring, most implementation effort of any phase | Phase 2 |
| 7 | Loading skeletons for positions list / symbol search / order actions | Low-Medium | Phase 1 |
| 8 | Changelog regeneration mechanism (replace hand-written "What's new" list) | Low, isolated to home.html + a small server-side helper | Independent of 1-7 |
| 9 | Fix the two confirmed logic smells opportunistically during their phase's migration: (a) collapse `positions.html`'s dual PIN-submit code paths into one `input`-length-based handler, (b) make the client-side P&L recompute in `positions.html` explicitly documented as an approximation (or, better, have the WS tick payload carry a server-computed P&L instead of raw LTP, removing the duplicate formula entirely) | Low-Medium, touches live-trading logic | Phase 2 |

**Suggested order if approved**: 0 → 1 → 2 → 6 → 9 (ship the trading pages fully improved first, since they're the highest-stakes and most recently-built) → 3 → 4 → 5 → 7 → 8.

---

## Open questions for you before any implementation begins

1. Does the console/app visual split (§4.1) match your intent, or would you rather unify everything into one visual language (all-light or all-dark)?
2. Is the `≥960px` trade.html side-by-side layout (§4.7) worth the implementation effort in Phase 6, or should desktop just stay a centered mobile-width column (simplest, zero new layout code)?
3. For the changelog (§4.7, Phase 8) — auto-generate from commit messages, maintain a small structured JSON/YAML list by hand with dates, or drop the section entirely?
4. Priority order — does the suggested sequence above match what you want first, or is there a specific page/problem you want addressed before the others?

# Product Design — Zerodha Trading Platform

**Status: proposal, not approved. No implementation until sign-off.**

This document redesigns the product from a blank page. It assumes nothing from the current HTML/CSS survives except the backend contract (routes, payload shapes, the `/ws/prices` protocol, PIN gate, SL/Target/Trailing semantics) — those are fixed by `src/server.py`, `src/execution/service.py`, and `src/execution/browser_price_relay.py`, and this document treats them as given, unchangeable inputs, not design decisions.

---

## 1. Product Vision

You open this on your phone between meetings, glance at one number — today's P&L — and know in half a second if you need to act. You open it on a MacBook with three monitors of charts already up elsewhere, and it becomes a fast, quiet execution surface: type a symbol, see the contract, set a stop, done, no ceremony. It never asks you to learn it. It never looks like a form. It looks like the thing a trader who also happens to have great taste would build for themselves.

The product is not "an AI-powered admin panel with a trading feature." It is a **trading terminal that happens to be reachable by an AI agent**, not the reverse. Every screen should read as software a trader would pay for, not documentation a developer would tolerate.

**North star:** if a screenshot of this app appeared next to a screenshot of Linear's issue view or TradingView's watchlist, it should not be obviously the cheaper one.

---

## 2. Design Philosophy

Five commitments, each one a filter every future decision passes through:

1. **Numbers are the interface.** Price, P&L, quantity, trigger — these are the content. Chrome, labels, borders, and icons exist only to make numbers faster to read and safer to act on. If a design choice competes with a number for attention, the number wins.
2. **Density with air.** Professional trading tools are dense — TradingView's watchlist, Bloomberg's terminal — but density is not the same as clutter. Every dense view here earns its density through alignment and rhythm (tabular numerals, consistent baseline grid, generous line-height on text, tight line-height on data rows), not through cramming.
3. **One motion vocabulary, used sparingly.** Motion confirms state changes a trader needs to trust (a tick moved, an order confirmed, a value that changed since you last looked). It never performs. No bouncing, no decorative parallax, no animated gradients behind real numbers.
4. **The interface disappears under intent.** The fastest path to "place this order" or "see this position" should require the fewest taps and the least reading. Every screen is judged by: how many decisions does a trader make before the number they care about is on screen and actionable.
5. **Consistency is a promise, not a style.** One spacing scale, one type scale, one color system, one interaction pattern for "confirm a destructive/financial action," used identically whether you're looking at the landing page or placing a ₹50,000 order. A user should never have to relearn a gesture between screens.

---

## 3. Visual Identity

**Personality:** quiet confidence. Not loud fintech-neon, not sterile enterprise-grey. Closest reference point in spirit (not in pixels): Linear's restraint crossed with TradingView's data trust crossed with Stripe Dashboard's typographic discipline.

**Core identity decisions:**
- **Dark-first, not dark-only.** Trading tools live in dark environments (multi-monitor desks, evening checks) more often than not, but this product must be excellent in light mode too — many traders check positions on a bright phone screen outdoors. Dark is the *default* and the *primary design target*; light is a fully-realized second theme, not an afterthought media query.
- **One accent color, used with restraint.** A single brand blue, reserved for primary actions, active navigation, and links. It never appears decoratively. Buy/sell green/red are the only other saturated colors in the system, and they are reserved exclusively for directional financial meaning — never used for anything else (no "green means success" for a form save, no "red means error" for a network failure; those get a neutral amber/grey treatment instead, so red *only ever* means "you are losing money or selling").
- **No gradients, no glow, no decorative background texture.** The current home.html's grid-background-plus-radial-glow is a "developer landing page" signature, explicitly the thing we're moving away from. Surfaces are flat. Depth comes from elevation (subtle shadow/border shifts) and from real data (a chart, a live number), never from CSS decoration standing in for content.
- **A wordmark, not a logo-in-a-box.** The current gradient-square-letter-avatar ("Z" in a blue-green gradient tile) reads as a hackathon-project favicon. Replace with clean wordmark typography — the product's name set in the UI typeface at weight, nothing else. Confidence needs no icon.

---

## 4. Color System

Two fully-realized themes, one token contract. All values below are semantic — implementation maps them to actual hex/OKLCH; the point of this document is the *system*, not the swatch.

```
Surface layers (4 levels of elevation, used consistently everywhere):
  --surface-0   canvas / page background
  --surface-1   resting card / panel
  --surface-2   raised element (modal, popover, active input)
  --surface-3   overlay scrim

Content:
  --content-primary     numbers, headings, primary text
  --content-secondary   labels, metadata, timestamps
  --content-tertiary    disabled, placeholder, least important text
  --content-inverse     text on top of a filled accent/buy/sell surface

Border:
  --border-subtle   default dividers, card edges
  --border-strong   focus rings, active input, emphasis

Brand:
  --accent            one blue, primary actions + active nav + links
  --accent-surface    accent at low opacity, for selected/active backgrounds

Directional (financial meaning ONLY — never repurposed):
  --buy / --long     directional green
  --sell / --short   directional red
  --buy-surface / --sell-surface   low-opacity backgrounds for badges/rows

Status (non-financial signals — deliberately distinct hues from buy/sell
so "the market moved against you" and "your request failed" never look
the same at a glance):
  --status-info      neutral blue-grey, informational
  --status-warning   amber, AMO/after-hours/attention states
  --status-caution   a third hue (not red) for "action needed but not
                      financial loss" — e.g. "PIN required," "connection
                      lost" — so a WebSocket disconnect never visually
                      reads as "you're losing money"
```

**Dark theme** is tuned for long viewing sessions: near-black surfaces (never pure `#000`, which causes halation against bright numbers), soft off-white text (never pure `#fff`), buy/sell greens and reds shifted slightly toward higher luminance than their light-theme counterparts so they hold contrast on dark surfaces without vibrating.

**Light theme** is tuned for outdoor/bright-screen legibility: surfaces are a soft off-white (never stark `#fff` — reduces glare), text is a true near-black for maximum contrast, buy/sell colors are deepened slightly (a pure saturated green/red on white can feel garish; a slightly desaturated, deepened version reads as more premium and is easier to hold a gaze on for P&L-watching).

**Rule inherited from the audit and kept intentionally:** color is never the *only* signal for direction. Every buy/sell/positive/negative value pairs its color with a glyph (▲/▼) or explicit sign (+/−), so the system remains legible for colorblind users and holds up in direct sunlight where color discrimination degrades before contrast does.

---

## 5. Typography System

**Two typefaces, each with one job:**
- **A humanist UI sans** for everything read as language — headings, labels, body copy, buttons. Must have a true, distinct bold and a real italic (for the rare emphasis case), excellent number legibility even though numbers aren't its main job.
- **A tabular/monospace face for every number that represents money, quantity, or an identifier** — price, P&L, quantity, order ID, trigger price, timestamps. This is the single highest-leverage typographic decision in the whole system: on a trading screen, numbers must never visually "jitter" as digits change width, and columns of numbers must align on their decimal point without manual padding. This is already half-instinctively present in the current `positions.html` (`font-variant-numeric: tabular-nums` is set) but undermined by using the UI font instead of a true monospace for that data — carry the *instinct* forward, fix the *execution*.

**Scale** (a restrained, deliberate set — not "whatever felt right per page," which is the current state across all 4 files):

| Role | Use | Weight |
|---|---|---|
| Display | Landing hero headline only — used once per product | Bold |
| Title-L | Page titles (Positions, Place Order) | Semibold |
| Title-M | Section headings, card titles | Semibold |
| Title-S | Sub-section headings | Semibold |
| Body-L | Primary readable copy, form labels-as-sentences | Regular |
| Body-M | Default body text, list item primary text | Regular |
| Body-S | Secondary/meta text, timestamps, helper text | Regular |
| Caption | Eyebrow labels, uppercase micro-labels | Semibold, tracked |
| Data-L | Hero numbers — a position's live P&L, the day's total | Semibold, tabular |
| Data-M | Inline numbers — prices in a list, quantities | Regular, tabular |
| Data-S | Dense table/list numeric cells | Regular, tabular |

**Rule:** every numeric value in the product uses a Data-* role, never a Body-* or Title-* role, even when it appears inline in a sentence ("Qty **125**"). This is the fix for the current inconsistency where prices render in the same font as prose across `trade.html`/`positions.html`.

---

## 6. Spacing System

A single 4px base unit, exposed as a restrained named scale rather than raw pixel literals scattered per file (the current state: 6+ hand-picked duration/spacing values per file, no shared constant anywhere):

```
space-1  = 4px   micro (icon-to-label gap)
space-2  = 8px   tight (within a control)
space-3  = 12px  default internal padding
space-4  = 16px  default gap between related elements
space-5  = 24px  gap between distinct groups
space-6  = 32px  section separation
space-7  = 48px  major section separation (desktop only)
space-8  = 64px  page-level top/bottom breathing room (desktop only)
```

**Density modes:** the same scale, two multipliers — `comfortable` (1×, default on mobile and for onboarding/marketing surfaces) and `compact` (0.75× on internal gaps only, never on tap-target sizing) for power-user surfaces like a dense positions list on a wide desktop monitor, toggleable per user preference later but shipping with sensible per-surface defaults on day one (landing/login = comfortable always; positions/trade = comfortable on mobile, compact available ≥1024px).

**Tap targets never shrink with density** — minimum 44×44pt hit area on every interactive element regardless of density mode or viewport, per Apple HIG and it's simply correct for a product where a mis-tap can place a trade.

---

## 7. Responsive Strategy

Not "does it fit" — **does the layout *use the shape of the screen it's on***. Three shape-classes, not device names:

| Shape class | Approx width | Behavior |
|---|---|---|
| Compact | up to 599px (phones) | Single column. One primary action visible at a time. Bottom-anchored primary actions (thumb reach). Full-screen modals, not sheets that feel like an afterthought. |
| Medium | 600–1023px (large phones landscape, iPads, small laptops) | Single primary column with room for a persistent secondary panel (e.g. order form + live preview side by side once there's width for both without either feeling squeezed). Navigation shifts from bottom/hamburger to a persistent side rail. |
| Expanded | 1024px+ (laptops, desktops, ultrawide) | Multi-column workspace. Positions can show as a real dense list/table, not stacked cards. Trade form + live quote + recent orders can coexist on one screen. On ultrawide (≥1600px), content gets a *third* column or wider margins with intentional whitespace — it must never just stretch a phone layout across a 34" monitor, which is the single most common way "responsive" web apps embarrass themselves on wide screens today. |

**Fluid within each class**, not just breakpoint-snapping — type scale, spacing, and (where it genuinely helps, like the positions list) column count interpolate smoothly rather than jumping at exact pixel boundaries wherever the design tooling allows it.

---

## 8. Mobile Strategy

Mobile is not "the small version" — for this product it is very plausibly the *primary* surface (a trader checking positions between meetings, on the train, at lunch). Design mobile first, literally: every flow is designed for compact width before it's adapted upward.

- **Thumb-zone primary actions.** Sell, Place Order, Confirm — these live in the bottom third of the screen, reachable one-handed, never requiring a stretch to a top-corner button (a real ergonomic problem with the current `trade.html`, whose primary CTA sits after a scrollable form and whose position depends on form length).
- **Progressive disclosure, not accordion-hunting.** SL/Target/Trailing today is a manually-toggled collapsed section (`▸ Add SL/Target`) — on mobile this becomes a natural step in a short guided flow (Symbol → Side & Size → Protection (optional) → Review), each step full-screen, swipe/tap forward, so a trader is never scanning a long single-page form on a 6" screen.
- **Live data survives interruption.** Phones lock, apps background, networks drop on trains. The WebSocket reconnect logic already exists (`positions.html`'s exponential backoff) — the design responsibility is to make "reconnecting" visually calm (a small persistent indicator, never a jarring full-screen error) and to make stale-data explicit (a dimmed/greyed number the instant data exceeds its staleness window, rather than a live-looking number that's secretly minutes old — closing a real trust gap the current design doesn't address at all).
- **No hover-dependent affordances.** Nothing in the current design relies on hover (good — it's an unconscious mobile-safe habit already), but this is stated explicitly as a permanent constraint: every interactive state must have a touch-equivalent (pressed, not hover) from day one of any new component.

---

## 9. Desktop Strategy

Desktop is not "mobile stretched wide" — it's where a trader with three monitors uses this as one *panel* of their setup, so it must be information-dense and fast, never spacious for spaciousness's sake.

- **Persistent side navigation** (not a hamburger, not a top bar competing for vertical space) — Positions, Trade, and a future Watchlist/Journal live in a slim, always-visible rail, matching the mental model of Linear's sidebar rather than a marketing site's top nav.
- **Positions as a real dense list**, not stacked cards — symbol, qty, avg, LTP, P&L, SL/Target status, actions, all in aligned columns with tabular numerals, sortable by column. Cards are a mobile pattern; a desktop trader wants to scan 20 positions in one glance, which a card grid actively fights against (confirmed problem: the current 3-up card grid inside each position card wastes horizontal space that a table would use for 3× the information density).
- **Trade form gets a live-preview companion panel** on the same screen (§4.7 of the prior engineering audit already identified this as the highest-value layout change — carried forward here as a first-class desktop pattern, not a nice-to-have) — no full-screen swap to a separate "confirm" view when there's abundant width to show both simultaneously.
- **Keyboard-first affordances**: `/` to focus symbol search (a pattern every one of the inspiration products uses — Linear, Raycast, TradingView), arrow-key navigation through search results and position lists (already exists for the trade.html dropdown — extend the *pattern*, not just the one instance, to every list in the product), `Esc` to close any modal/panel, `Enter` to confirm the focused primary action.
- **Ultrawide gets intent, not stretch.** Past 1600px, add a third contextual column (e.g. a live order-book/recent-activity feed alongside positions) rather than letting existing columns balloon to uncomfortable line lengths.

---

## 10. Navigation Architecture

**One navigation model, everywhere** — the current split (trade/positions have a 2-item nav; home/login have none) is replaced entirely.

**Structure:** Home (product overview / connect an AI client) · Positions · Trade · Session (login/account state) — four top-level destinations, always the same four, always in the same order, present on every screen at every shape-class:

- **Compact (mobile):** bottom tab bar, 4 items, icon + label, current tab indicated by fill/weight change (not just a color shift, so it holds up for colorblind users and in bright light) — the standard, correct mobile pattern (Robinhood, every serious mobile trading app) that this product currently has zero equivalent of.
- **Medium/Expanded (tablet/desktop):** left side rail, same 4 items, collapsible to icon-only on narrower "Medium" widths, expanded with labels on "Expanded."
- **Session state is always visible but never loud** — a small persistent indicator (connected/guest/logged-out) in the nav itself, not a separate card competing for attention on the home page the way it does today.

**No more deep-link-only connections between pages.** Today, `/positions`' only path back to `/` or `/login` is nonexistent — the new nav model means every page is always one tap from every other page, which alone resolves problem P4 from the prior audit.

---

## 11. Page Hierarchy

```
/                    Home — product overview + "connect an AI client" (secondary
                     audience: developers). For the primary audience (a trader
                     with the URL bookmarked), this is effectively a dashboard:
                     today's P&L at a glance, quick actions to Trade/Positions.
/positions           Primary workspace — this is where a returning user lands
                     mentally, even if / is the literal browser history entry.
/trade               Focused execution surface — get in, place the order,
                     get out. Never the place you "browse."
/login               Utility page — get in, get your key, get out. Should take
                     under 30 seconds for a returning user.
```

The current product treats `/` as equally important to `/trade`/`/positions` — the redesign explicitly demotes it to "overview + one-time setup for the AI-client audience," and promotes `/positions` to the de facto home screen for the trading audience (reflected in nav ordering and in what the "Home" screen surfaces first for a returning, PIN-known user — see §20).

---

## 12. Component Library

A deliberately small, composable set — not a copy of shadcn/Material/Bootstrap, but the minimum vocabulary this specific product needs, each with one job:

1. **Button** — primary (filled accent), secondary (outlined), ghost (text-only), destructive (sell/cancel — filled red only for the single most irreversible action on a screen, outlined red for lesser destructive actions). One size scale (S/M/L), consistent padding-to-text ratio, one loading state (label swaps to a spinner-plus-verb, e.g. "Placing…", never a bare spinner with no text — the current pattern, kept, generalized).
2. **Data Card** — the atomic unit for a position, an order, a search result. One visual shell, contents vary. Contains: identity (symbol + tags), a data row (tabular numerals), optional status badges, optional actions. Same shell renders as a mobile card and (via CSS, not a separate component) collapses into a table row at Expanded width.
3. **Input** — text, numeric (with proper `inputmode`), PIN (masked, large touch target, numeric keypad trigger). One focus treatment everywhere: a visible ring in `--accent`, meeting WCAG contrast against every surface color in both themes.
4. **Badge** — one shape, six semantic color mappings (buy, sell, info, warning, caution, neutral) — replacing the current 8+ ad-hoc pill/tag variants across home.html and positions.html.
5. **Banner** — inline success/error/info feedback, one component replacing the current `.alert`/`.msg` split-naming duplication.
6. **Modal / Sheet** — full-screen on Compact, centered dialog on Medium/Expanded, one open/close animation, focus-trapped, Escape-to-close, backdrop-click-to-close where the action isn't destructive (never for an order-confirm step).
7. **Skeleton** — a shimmer placeholder matching the shape of the Data Card / list row it's replacing, used for every async load (positions fetch, symbol search, order placement) — currently nonexistent anywhere in the product.
8. **Live Value** — a purpose-built component (not a generic `<span>`) for any number that updates over the WebSocket: owns its own tabular-numeral formatting, its own directional color+glyph, its own staleness-dimming behavior, and its own "just changed" micro-animation (a brief, subtle background flash — refined from the current border-flash-on-card pattern, moved to be scoped to the value itself so a card with 3 numbers doesn't flash as one undifferentiated block when only one number moved).
9. **Nav Rail / Tab Bar** — one component, two renderings (side rail / bottom bar) selected by shape-class, described in §10.
10. **Stepper** — the mobile guided-flow container for multi-step processes (order placement's Symbol → Side/Size → Protection → Review), reusable for any future multi-step flow (a future "connect a new broker" flow, for instance).

---

## 13. Animation Philosophy

Every motion in the system maps to exactly one of four intents — nothing animates without belonging to one of these:

1. **Orientation** — helping you understand where you are or where something went (a page transition, a modal opening from the element that triggered it, a tab's content sliding in from the direction of the tab you tapped). Duration: 200-280ms, standard ease-out.
2. **Feedback** — confirming an action registered (button press states, a value's "just updated" flash, a success checkmark). Duration: 100-150ms for press, 300-400ms for a flash/confirmation, quick enough to never feel like it's making you wait.
3. **Continuity** — data that's actually live doing what live data does (a price ticking, a P&L number counting toward its new value rather than snapping — a *subtle* numeric transition, not a slot-machine spin). This is the one category the current design almost has right (the tick-flash exists) and the one place a modern trading UI most needs to feel alive without feeling gimmicky.
4. **Absence-handling** — loading skeletons' shimmer, empty-state illustrations settling in. Slow, low-amplitude, meant to be looked at without demanding attention (unlike Feedback, which is meant to be noticed).

**Hard rules:**
- Nothing animates purely for entrance delight on a page a user will see repeatedly (the current staggered `.a1`-`.a6` fade-up on `home.html` is exactly this — charming once, an annoyance on the 50th visit; kept only for a true one-time context like a first-run/onboarding moment, not for every page load).
- Every animation respects `prefers-reduced-motion: reduce` by collapsing to an instant state change — audited as completely absent today, non-negotiable going forward.
- No animation blocks interaction — a user can always interrupt a mid-flight transition by tapping the next thing they want.

---

## 14. Interaction Guidelines

- **One confirmation pattern for money-moving actions.** Placing an order, modifying a stop, selling a position — all use the same interaction shape: the action is visible and named accurately on the trigger (never a bare icon for "Sell"), a single deliberate confirming tap is required (already the correct call made this session for one-tap-sell-with-PIN — generalized here as the *standard*, not a one-off), and the result is communicated inline at the point of action, never via a separate page navigation or a browser-native `alert()`/`confirm()` (both used today in places and both are jarring, blocking, and unstyleable).
- **Destructive/irreversible actions get a visually distinct trigger** (outlined or ghost red, never accent blue) so "Sell" is never one misread away from being confused with "View" or "Modify" — a real current risk, since `positions.html`'s three action buttons today share nearly identical visual weight.
- **Every async action shows its own state on itself**, not globally — a "Sell" button becomes "Selling…" only on the card it belongs to; other cards on screen remain fully interactive. (Already correctly done for sell in the current `positions.html` — kept and generalized to every other async trigger, including symbol search and modify.)
- **Errors are actionable, not just reported.** An error state always offers the next step (Retry, Edit, Dismiss) inline, never leaves the user staring at red text with no button (the current gap: a failed `/positions/data` fetch shows text with no retry affordance).
- **Optimistic where safe, honest where not.** A "Sell" tap can optimistically dim/grey the position immediately (feels instant) while the network call is in flight, but must clearly roll back and restore + explain if the order is rejected — never leave the UI in a state that implies a trade happened when it didn't.

---

## 15. Accessibility Guidelines

Non-negotiable baseline, audited as entirely absent today:

- **Visible focus indication** on every interactive element, using `:focus-visible` (not `:focus`, which would show the ring on mouse clicks too — annoying) with a ring in `--accent` at a contrast ratio that passes WCAG AA against every surface color in both themes.
- **`aria-live="polite"` regions** for anything that updates without user action: the WebSocket connection-status text, and — carefully scoped, not on every single tick, which would be an unusable firehose for screen-reader users — a periodic/summary announcement of position P&L changes rather than per-tick.
- **Color is never the sole signal.** Every directional/status color pairs with a glyph or text (▲/▼, "AMO", "Disconnected") as established in §4.
- **Full keyboard operability**: every mouse/touch interaction (tab switch, modal open/close, list navigation, symbol pick from search) has a keyboard equivalent, extending the arrow-key pattern that already exists for one component (trade.html's dropdown) to the whole product.
- **Minimum 44×44pt touch targets**, **4.5:1 text contrast minimum** (body text), **3:1 minimum** for large/data text, in both themes, verified per-theme (not assumed to transfer from dark to light or vice versa).
- **Reduced motion respected everywhere**, per §13.
- **Screen-reader-sensible labels** on icon-only controls (a "…" deep-link button, a copy-to-clipboard icon) — currently several icon-only buttons across the product have no accessible name beyond their visual glyph.

---

## 16. Empty States

Every list/data surface gets a designed empty state, not a bare sentence:

- **No positions** — not "No open positions right now" (current, functional but flat) but a state that still *does something*: a clear illustration-free (icon + short copy, staying on-brand — no cutesy mascot illustrations, which would clash with the "premium, quiet confidence" identity) message plus a direct action (**Place your first order →**), turning a dead end into a next step.
- **No search results** — distinguish "you haven't typed enough yet" from "we searched and found nothing" from "search failed" — three different states currently collapsed into similar-looking blank dropdowns.
- **No active SL/Target on a position** — currently a disabled button with a title tooltip (invisible on mobile, where hover tooltips don't exist at all) — replaced with visible inline text next to the action ("No stop set"), always legible, no hover dependency.
- **Guest/logged-out home state** — currently a warning-colored card; redesigned as a calm, inviting state (this is a *normal*, expected state for a new visitor, not a warning) with the primary action (Log in / Continue as guest) as the visual focus of the screen rather than a secondary card.

---

## 17. Loading States

Currently: almost universally absent (a button relabels itself; nothing else changes). Redesign:

- **Skeleton screens matching final content shape** for: positions list (skeleton Data Cards, count matching a sensible default like 3), symbol search results (skeleton rows appearing the instant a debounced search fires, before the response arrives), the trade preview panel (skeleton numbers while `/trade/preview` is in flight).
- **Inline, scoped spinners** for button-triggered actions (Place Order, Sell, Modify, Save) — button retains its size (no layout shift when text is replaced by a spinner+verb), disabled state prevents double-submission (already correct in current code, kept).
- **A connecting/reconnecting state for the WebSocket** that is calm and persistent (a small dot + label in the nav or page header, not a full-page blocking state) — live data staleness is communicated at the *value* level (dimmed number, per §8) rather than by blocking the whole page.

---

## 18. Error States

- **Field-level validation errors** appear inline, next to the specific field, the instant it's clear the input is invalid (e.g. a negative quantity) or on blur for anything requiring a network check — never bundled into one generic banner at the bottom of a long form, which is the current pattern and forces a user to hunt for which field is actually wrong.
- **Request-level errors** (a rejected order, a failed fetch) appear as an inline Banner at the point of action, with the actual reason surfaced when the backend provides one (the backend already returns specific messages like "Symbol not found in NSE EQUITY instruments" — today's UI mostly does display these, correctly; the redesign's job is to make the container for that message consistent and dismissible everywhere, and to add a Retry action wherever the failure was transient, i.e. network/5xx, versus a validation failure requiring different input).
- **Catastrophic errors** (server unreachable) get a distinct, honest full-page state — never a silent blank screen, never a raw stack trace or fetch exception message shown to the user (a real current gap: `catch(e){ show("pinMsg","err", String(e)); }` surfaces a raw JS error object to the trader if, say, `fetch` itself throws).

---

## 19. Trading Workflow UX

This is the section that most directly touches the money-moving path — designed for zero ambiguity and minimum friction, in that order.

**Placing an order (redesigned flow, mobile):**
1. **Symbol** — search-first screen, the search box is the only thing on screen with focus, results appear inline below as you type (existing debounce/abort logic kept, it's correct), tapping a result advances immediately — no separate "confirm your symbol" tap needed.
2. **Side & Size** — large BUY/SELL toggle (unmistakably distinct colors + icons, not just a border-color swap as today), quantity stepper with lot-size awareness surfaced as primary information, not a small hint line beneath the field.
3. **Protection (optional, skippable)** — SL/Target/Trailing presented as an explicit, named step a user can skip with one tap ("Skip — place without a stop"), not a collapsed disclosure they might not notice exists (a real current risk: `▸ Add SL/Target (optional)` is easy to miss entirely, meaning a large fraction of users may never discover this exists).
4. **Review & Place** — one screen, every parameter visible at once in a clean summary (kept from current `renderSummary`, restyled with tabular numerals and clear labels), the PLACE button is the only accent-colored element on the screen, secondary "Back" is visually quiet.

**Placing an order (desktop, ≥1024px):** steps 1-3 collapse into one continuously-visible form (no step navigation needed — there's room for the whole thing), with a live-updating Review panel beside it that reflects every field change in real time, removing step 4 as a separate screen entirely — the "review" *is* the persistent right-hand panel.

**Monitoring positions:** the position list is the main event, not a secondary "view what happened" page. Total P&L is the single largest, most prominent number in the header of this screen at all times (currently: a "Total P&L" stat card competing equally with "Open positions" count — redesigned so P&L visually dominates, since it's the number that actually matters). Per-position, the LTP and P&L are the visually loudest data; qty/avg/exchange are secondary metadata rendered smaller and quieter.

**Modifying a stop:** the current bottom-sheet modal pattern is kept (it's the one modal in the current product and it's the right pattern for this specific action — a quick, contextual edit that shouldn't feel like leaving the page) but restyled onto the unified system, with clearer visual distinction between "this is the current value" and "this is what you're about to change it to."

**Trust signals throughout:** every screen showing a live number carries a visible "last updated"/"live" affordance (the connection-status dot, kept and elevated from a small text label to a first-class, always-visible element) — a trader must never wonder whether the number on screen is current.

---

## 20. Landing Page Redesign (`/`)

Reframed per §11: this page serves two audiences, and the redesign makes the split explicit rather than blended into one long scroll.

**For a returning trader** (the primary audience, detected via existing PIN/session state — same detection the current session-status check already performs): the page opens with **today's snapshot** — total P&L, open position count, a "Continue to Positions →" primary action — essentially a compressed preview of `/positions`, so landing on `/` is never a dead end before the "real" app.

**For a new visitor / developer connecting an AI client** (secondary audience): below that snapshot (or, for a user with no session at all, as the first thing shown), a clean, quiet product overview — what this is, the two ways in (trade directly via the web app, or connect an AI agent via MCP), followed by the connection guide — restyled onto the unified system, tab-switcher using the shared component from §12, code blocks using the Data-* monospace type role from §5.

**Explicitly removed:** the grid-and-glow decorative background (§3), the gradient-letter logo tile (§3), the staggered per-section entrance animation on every single visit (§13) — replaced with a single, calm entrance the first time a session starts, never repeated.

**Explicitly kept, restyled:** the guest-vs-full-access explainer (genuinely useful information, currently just poorly dressed), the changelog concept (restructured per the prior audit's Phase 8 recommendation — this document doesn't re-litigate that mechanism, only confirms it belongs on this page, likely below the fold for the trading audience).

---

## 21. Login Redesign (`/login`)

Goal: fastest possible re-entry for a returning user, a trustworthy first impression for a new one — under the same visual system as everywhere else, no more standalone dark-console styling.

- **Single-purpose screen.** Credential form, nothing else competing for attention (kept from current design — this part is already correctly minimal).
- **The post-login setup guide is demoted, not removed.** Today, a successful login immediately buries the person in a 5-tab "connect your AI client" guide before they've even seen the product — for a trader who just wants to place an order, this is friction, not help. Redesign: on success, show a clear confirmation + **direct path into the app** ("Continue to Positions →") as the primary action; the API-key-and-setup-guide content moves to a secondary, clearly-labeled expandable section ("Connect an AI client instead") for the audience that actually wants it, rather than being forced on everyone.
- **The API key reveal pattern (blur-until-tap, copy button) is good and is kept**, restyled onto the unified component set — this is a genuinely well-considered piece of the current design and should survive the rewrite intact in behavior.
- **Guest entry is equally prominent**, not a smaller/quieter link beneath the primary form — for the AI-client audience, guest access is often the *first* choice, not a fallback, and should read that way.

---

## 22. Trade Page Redesign (`/trade`)

Covered in detail in §19's workflow section; summarized here as the page-level shape:

- **Mobile:** the 4-step guided flow (§19). Bottom-anchored primary action at every step. No visible "form" at all in the traditional sense — it reads as a sequence of small decisions, not a document to fill out.
- **Desktop (≥1024px):** single continuous form + live preview panel, no step navigation, described in §19.
- **Persistent context:** the page always shows, in a quiet header, what you're about to do in plain language once past step 1 ("Buying 125 NIFTY 24200 CE") — so at every point in the flow you're oriented without having to scroll back up.
- **The deep-link-from-positions behavior is kept** (arriving with a pre-filled symbol, defaulted to Sell, Protection step pre-expanded) — this is genuinely good, considered UX from the current build and survives unchanged in *behavior*, only in visual execution.

---

## 23. Positions Page Redesign (`/positions`)

Promoted to the primary workspace per §11:

- **Mobile:** a vertically prioritized layout — P&L hero number first (large, live, tabular, with the connection-status indicator directly beside it), then the position list as Data Cards (§12), each card's LTP/P&L visually dominant over its metadata, actions (Sell/Modify) as clearly differentiated buttons per §14, the "…" overflow link demoted to a small icon-only affordance with a proper accessible label (§15).
- **Desktop (≥1024px):** the list becomes a real dense table — columns for Symbol, Exchange, Qty, Avg, LTP, P&L, Protection status, Actions — sortable, with the P&L hero number staying visible in a sticky header above the table as you scroll (closing the "P&L scrolls out of view" gap identified in the prior audit).
- **Live update behavior:** the Live Value component (§12) owns per-cell flash-on-change, scoped tightly (only the LTP and P&L cells flash, not the whole row/card) so a busy multi-position list doesn't turn into a distracting strobe.
- **Staleness is explicit** (§8): any position whose price hasn't ticked within the expected window visually dims, with a small "stale" indicator — never silently shows an old number as if it were current.
- **Modify stays a bottom-sheet/dialog** (kept per §19), Sell stays one-tap-with-PIN (kept, generalized per §14 as the product's standard confirmation pattern), both restyled onto the unified component set with clearer visual weight distinction between the two actions and the safe "…" navigation link.

---

## 24. Future Scalability

The system is designed to absorb, without a redesign, at minimum:

- **A watchlist page** — same Data Card/table duality as Positions, same nav rail slot pattern (§10), same Live Value component for streaming quotes on symbols not currently held.
- **A trade journal / order history page** — same table pattern as the desktop Positions view, same empty/loading/error state components, no new visual vocabulary required.
- **A charting surface** — the one genuinely new component category the current system doesn't anticipate; reserved as a clear gap here so a future chart integration is scoped as "add a Chart component to the library" rather than "redesign the product to fit a chart."
- **Additional brokers/exchanges** (the MCX/Kite conversation earlier this session is a live example) — the design system has no broker-specific visual assumptions; a new broker is a new data source feeding the same Data Card/table/Live Value components, not a new visual language.
- **Multi-account or team use** — the nav/session model (§10) has room for an account switcher without restructuring, since session state is already an isolated, first-class nav element rather than a page-specific card.
- **Dark/light theme is a first-class system property from day one** (§4), not a bolt-on, so future surfaces inherit both automatically rather than needing per-page theme work the way `home.html`/`login.html` currently lack any light-mode treatment at all.

---

## Open questions for you before implementation begins

1. Does "Positions as primary home, `/` demoted to overview + snapshot" (§11, §20) match your intent, or should `/` remain the primary landing destination even for returning traders?
2. The 4-step mobile order-placement flow (§19) is a meaningfully different interaction model from today's single scrolling form — worth the added complexity, or would you prefer the form stay single-screen on mobile too, just restyled?
3. Desktop positions-as-a-table (§23) versus keeping cards everywhere at every width — tables are denser and more "trading terminal," cards are softer and more "consumer app." Which direction fits your intent for this product?
4. Any hard preference on the single accent brand color, or is that open for a visual exploration pass once this direction is approved?

> **Archived design source.** This blueprint's page layouts and interaction
> rules were implemented across `src/ui/*.html`. The "not approved" status
> line below predates that implementation and is kept for historical
> accuracy, not as a current statement.

# UX Blueprint — Zerodha Trading Platform

**Status: proposal, not approved. No implementation code in this document.**

This blueprint makes `PRODUCT_DESIGN.md` concrete: exact layout, exact hierarchy, exact flow, for every page, at three breakpoints. It answers the four open questions left at the end of the product design doc with working defaults so the wireframes below aren't hedged — each default is called out explicitly where it matters, and any of them can be overturned without touching the rest of the document.

**Defaults assumed for this pass** (flag if wrong, nothing below is locked):
1. `/positions` is the primary workspace; `/` opens with a snapshot for a known session, full overview for a new one.
2. Mobile order placement uses the 4-step guided flow.
3. Desktop positions render as a dense table; mobile stays cards.
4. Accent color treated as a single deep blue for this pass — a distinct visual-exploration deliverable (actual swatches, not ASCII) should follow this document once the layout direction is approved, since color can't be meaningfully reviewed in text wireframes.

**Wireframe key** used throughout:
```
[Button]      tappable/clickable action
{Input___}    text/numeric input field
<Icon>        icon-only element
▓▓▓           filled/active/emphasized element
░░░           skeleton/loading placeholder
···           live-updating value
=== / ---     section divider (heavy / light)
```

---

## Page 1 — Home (`/`)

### 1.1 Navigation flow
```
Entry points:  bookmarked URL · browser back from any page · nav rail/tab "Home"
Exit points:   [Continue to Positions] → /positions (known session)
               [Place an order] → /trade
               [Log in] → /login
               [Connect an AI client ▾] → expands in place, no navigation
Session-aware: unauthenticated/no-PIN → overview-first layout (§1.5 "new visitor")
               known PIN session → snapshot-first layout (§1.5 "returning trader")
```

### 1.2 Information hierarchy (returning trader)
```
1. Today's P&L (largest element on screen)
2. Open position count + quick nav to Positions/Trade
3. Session state (quiet, persistent, in nav — not a card)
4. [below the fold] product overview + AI-client connection guide
5. [below that] changelog
```

### 1.3 Information hierarchy (new visitor)
```
1. Product identity (wordmark, one-line description)
2. The two ways in: [Trade directly] vs [Connect an AI agent]
3. Guest vs full-access explainer
4. Connection guide (tabbed)
5. Changelog
```

### 1.4 Desktop wireframe (≥1024px) — returning trader
```
┌─────┬──────────────────────────────────────────────────────────────────┐
│ NAV │  Today                                              [●Live]     │
│     │  ┌──────────────────────────────────────────────────────────┐   │
│ Home│  │  Today's P&L                                             │   │
│▓Home│  │  +₹12,480                                    ▲ +2.3%     │   │
│Trade│  │  4 open positions                                        │   │
│Pos'ns│  │  [Continue to Positions →]        [Place an order →]     │   │
│     │  └──────────────────────────────────────────────────────────┘   │
│─────│                                                                   │
│Sess:│  ─────────────────────────────────────────────────────────────  │
│●PIN │  About this platform                                             │
│ set │  One-line description of the trading terminal + AI-agent access. │
│     │                                                                   │
│     │  ┌───────────────────────┐  ┌───────────────────────┐            │
│     │  │ Trade directly         │  │ Connect an AI agent    │            │
│     │  │ Search, buy/sell,      │  │ MCP endpoint, guest or  │            │
│     │  │ SL/Target/Trailing     │  │ full access             │            │
│     │  │ [Open Trade →]         │  │ [View setup guide →]    │            │
│     │  └───────────────────────┘  └───────────────────────┘            │
│     │                                                                   │
│     │  [claude.ai] [Claude Code] [Claude Desktop] [Cursor] [Postman]   │
│     │  ┌──────────────────────────────────────────────────────────┐   │
│     │  │ step 1 · step 2 · step 3  (tab content for selected)      │   │
│     │  └──────────────────────────────────────────────────────────┘   │
│     │                                                                   │
│     │  ───────────────────────────────────────────────────────────    │
│     │  What's new                                                      │
│     │  · Live positions with WebSocket prices                         │
│     │  · SL / Target / Trailing SL on orders                          │
│     │  · Instant order-fill alerts                                    │
└─────┴──────────────────────────────────────────────────────────────────┘
```

### 1.5 Tablet wireframe (600–1023px)
```
┌──────────────────────────────────────────────┐
│ ≡  Zerodha              [●PIN set]  <Session> │  ← collapsed icon rail, top
├──────────────────────────────────────────────┤
│  Today's P&L                                  │
│  +₹12,480                        ▲ +2.3%      │
│  4 open positions                              │
│  [Continue to Positions →]                     │
│  [Place an order →]                            │
│                                                 │
│  ────────────────────────────────────────────  │
│  About this platform                           │
│  One-line description.                         │
│                                                 │
│  ┌────────────────────┐ ┌────────────────────┐ │
│  │ Trade directly      │ │ Connect an AI agent │ │
│  │ [Open Trade →]      │ │ [Setup guide →]     │ │
│  └────────────────────┘ └────────────────────┘ │
│                                                 │
│  [claude.ai][CC][Desktop][Cursor][Postman]     │
│  ┌───────────────────────────────────────────┐ │
│  │ tab content                               │ │
│  └───────────────────────────────────────────┘ │
│  ────────────────────────────────────────────  │
│  What's new                                    │
│  · entry · entry · entry                       │
└──────────────────────────────────────────────┘
```

### 1.6 Mobile wireframe (≤599px)
```
┌───────────────────────────┐
│ Zerodha         <Session> │
├───────────────────────────┤
│                            │
│  Today's P&L               │
│  +₹12,480                  │
│  ▲ +2.3% · 4 positions      │
│                            │
│  [ Continue to Positions ] │
│  [ Place an order ]        │
│                            │
│  ─────────────────────    │
│  About this platform       │
│  One-line description.     │
│                            │
│  ┌───────────────────────┐│
│  │ Trade directly         ││
│  │ [Open Trade →]         ││
│  └───────────────────────┘│
│  ┌───────────────────────┐│
│  │ Connect an AI agent    ││
│  │ [Setup guide →]        ││
│  └───────────────────────┘│
│                            │
│  [claude.ai ▾]             │  ← tabs collapse to a select on mobile
│  ┌───────────────────────┐│
│  │ tab content            ││
│  └───────────────────────┘│
│  ─────────────────────    │
│  What's new                │
│  · entry                   │
│  · entry                   │
├───────────────────────────┤
│ [Home][Pos][Trade][Sess]  │  ← bottom tab bar
└───────────────────────────┘
```

### 1.7 User interaction flow
```
Land on / → session check (existing /auth/status + PIN-known check)
  ├─ known session  → snapshot card renders first, real numbers fetched async
  ├─ no session     → overview renders first, no snapshot card at all
  └─ fetch fails     → snapshot card shows its own inline error, rest of page unaffected

Tap [Continue to Positions] → /positions
Tap [Place an order]        → /trade
Tap a client tab            → in-place content swap, no navigation, no reload
Tap [Log in]                → /login
```

### 1.8 Component placement
```
Nav Rail/Tab Bar   — persistent, all breakpoints (§10 of PRODUCT_DESIGN.md)
Data Card          — snapshot card (P&L + count + 2 actions)
Badge              — "Live" indicator, session-state pill
Button (primary)   — Continue to Positions, Place an order
Button (secondary) — client-guide tabs
Banner             — snapshot-fetch error (inline, scoped to that card only)
```

### 1.9 Empty state
```
New visitor, no session at all:
  Snapshot card is entirely absent (not shown empty — a P&L card with no
  session behind it is a category error, not an empty state). Overview
  layout (§1.3) is simply the default content, not a fallback.

Known session, zero positions:
  Snapshot card still renders, showing:
    "No open positions" · [Place your first order →]
  instead of a P&L figure — never shows "₹0" as if that were a real,
  meaningful zero.
```

### 1.10 Loading state
```
┌──────────────────────────────────────────────────┐
│  ░░░░░░░░░░░░░░░░░░                               │
│  ░░░░░░░░░░░░  ░░░░░░░░                           │
│  ░░░░░░░░░░░░░░░░░░░░░░░░░░                       │
│  [░░░░░░░░░░░░░░]  [░░░░░░░░░░░░░]                │
└──────────────────────────────────────────────────┘
Skeleton shape matches the final snapshot card exactly (label lines,
number line, two button-shaped placeholders) — never a generic spinner
replacing the whole card.
```

### 1.11 Error state
```
┌──────────────────────────────────────────────────┐
│  ⚠  Couldn't load today's snapshot                │
│     [Retry]                                       │
└──────────────────────────────────────────────────┘
Scoped to the snapshot card only. Rest of the page (nav, overview
content, client guide) renders normally and is fully interactive —
a snapshot failure never blocks the whole page.
```

---

## Page 2 — Login (`/login`)

### 2.1 Navigation flow
```
Entry points:  nav "Session" tap when logged out · direct /login link ·
               redirected here by an auth-gated action elsewhere (none exist
               today outside the OAuth flow, but the pattern should hold)
Exit points:   [Continue to Positions] → /positions (post-success primary path)
               [Connect an AI client instead ▾] → expands in place (secondary path)
               [Continue as guest] → guest token flow, stays on page with result shown
```

### 2.2 Information hierarchy
```
1. Credential form (Client ID, Password, TOTP) — the only thing competing
   for attention pre-login
2. Post-success: confirmation + [Continue to Positions] as the loud action
3. Post-success, secondary: collapsed "Connect an AI client instead" section
4. Always-visible, quiet: [Continue as guest] — equal visual weight to the
   form's submit action, not a smaller afterthought link
```

### 2.3 Desktop wireframe (≥1024px)
```
┌─────┬──────────────────────────────────────────────────────────────────┐
│ NAV │                                                                   │
│     │                    ┌───────────────────────────┐                 │
│Home │                    │  Zerodha                    │                │
│Trade│                    │                             │                │
│Pos'ns│                   │  Sign in                    │                │
│     │                    │  Enter your Kite credentials│                │
│─────│                    │                             │                │
│Sess:│                    │  Client ID                  │                │
│ —   │                    │  {ZK1234______________}     │                │
│     │                    │                             │                │
│     │                    │  Password                   │                │
│     │                    │  {••••••••______________}   │                │
│     │                    │                             │                │
│     │                    │  TOTP                        │                │
│     │                    │  {••••••______________}     │                │
│     │                    │                             │                │
│     │                    │  [    Sign in securely    ]  │                │
│     │                    │                             │                │
│     │                    │  🔒 Credentials go directly  │                │
│     │                    │     to the server            │                │
│     │                    │                             │                │
│     │                    │  ─────────  or  ─────────   │                │
│     │                    │                             │                │
│     │                    │  [   Continue as guest    ]  │                │
│     │                    └───────────────────────────┘                 │
└─────┴──────────────────────────────────────────────────────────────────┘
```

### 2.4 Desktop wireframe — post-success state
```
┌─────┬──────────────────────────────────────────────────────────────────┐
│ NAV │                    ┌───────────────────────────┐                 │
│     │                    │  ✓ Signed in                │                │
│Home │                    │  Zerodha session is active   │                │
│Trade│                    │                              │                │
│Pos'ns│                   │  [   Continue to Positions →  ]              │
│     │                    │                              │                │
│─────│                    │  ▾ Connect an AI client instead              │
│Sess:│                    │                              │                │
│●PIN │                    └───────────────────────────┘                 │
└─────┴──────────────────────────────────────────────────────────────────┘

expanded state of "Connect an AI client instead":
                    ┌───────────────────────────┐
                    │  ✓ Signed in                │
                    │  [   Continue to Positions →  ]              │
                    │                              │
                    │  ▴ Connect an AI client instead              │
                    │  ┌──────────────────────┐   │
                    │  │ Your API Key           │   │
                    │  │ ▓▓▓▓▓▓▓▓▓▓▓▓ [👁][Copy] │   │
                    │  └──────────────────────┘   │
                    │  [claude.ai][CC][Desktop]... │
                    │  ┌──────────────────────┐   │
                    │  │ tab content            │   │
                    │  └──────────────────────┘   │
                    └───────────────────────────┘
```

### 2.5 Tablet wireframe (600–1023px)
```
Same card, same content, card width fluid (min 420px / max 480px),
centered, side rail collapses to icon-only. Structurally identical to
desktop — this page has no meaningful tablet-specific layout change,
since a centered form card is already the correct pattern at this width.
```

### 2.6 Mobile wireframe (≤599px)
```
┌───────────────────────────┐
│ Zerodha                    │
├───────────────────────────┤
│                            │
│  Sign in                   │
│  Enter your Kite creds     │
│                            │
│  Client ID                 │
│  {ZK1234_______________}   │
│                            │
│  Password                  │
│  {•••••••______________}   │
│                            │
│  TOTP                      │
│  {••••••_______________}   │
│                            │
│  [   Sign in securely   ]  │  ← full-width, bottom-anchored on
│                            │     small screens if form is above fold
│  🔒 Credentials go direct  │
│     to the server          │
│                            │
│  ────── or ──────          │
│  [   Continue as guest  ]  │
├───────────────────────────┤
│ [Home][Pos][Trade][Sess]  │
└───────────────────────────┘
```

### 2.7 User interaction flow
```
Load /login → form focused on Client ID (if empty) or Password (if
  Client ID pre-filled from a prior partial attempt — existing
  {prefill_user_id} server behavior, kept)
Submit → button becomes "Signing in…" + inline spinner, fields lock
  ├─ success → card content swaps to post-success state (§2.4), no navigation
  ├─ bad credentials → inline Banner above the form, fields unlock, TOTP
  │    field cleared (never re-submit a stale/expired TOTP), focus returns
  │    to Password
  └─ network/server error → inline Banner, "Retry" implicit (fields still
       editable, just resubmit)
Tap [Continue as guest] → inline result (token shown in place, same card),
  never a separate page
Tap [Continue to Positions] (post-success) → /positions
Tap "Connect an AI client instead" → expands in place, no navigation
```

### 2.8 Component placement
```
Data Card    — the single form card (auth surfaces are the one context
               where a centered, isolated card is correct — not a Data
               Card in the positions/trade sense, but the same visual
               shell/elevation language)
Input        — 3 fields (text, password, password-numeric for TOTP)
Button       — primary (Sign in), secondary/ghost (Continue as guest,
               equal size to primary — see §2.2)
Banner       — error/success feedback
Badge        — "🔒" trust note (icon + text, not just an icon)
```

### 2.9 Empty state
```
Not applicable — this page has no list/data surface, only a form.
```

### 2.10 Loading state
```
[  ⟳ Signing in…  ]   ← button-scoped spinner+verb, fields disabled,
                          no full-page overlay, no layout shift
```

### 2.11 Error state
```
┌──────────────────────────────┐
│ ⚠ Incorrect password or TOTP  │
└──────────────────────────────┘
  Client ID
  {ZK1234______________}
  Password
  {______________________}     ← cleared, refocused
  TOTP
  {______________________}     ← cleared (never resend a stale code)
  [    Sign in securely    ]
```

---

## Page 3 — Trade (`/trade`)

### 3.1 Navigation flow
```
Entry points:  nav "Trade" tap · [Place an order] from Home ·
               deep link from Positions "…" action (pre-filled symbol,
               side=SELL, Protection step pre-expanded)
Exit points:   successful place → inline confirmation + [View in Positions →]
               [Cancel]/back at any step → previous step (mobile) or
               simply stop editing (desktop, since there's no step nav)
```

### 3.2 Information hierarchy — mobile guided flow
```
Step 1 Symbol:        search box (only focused element) > results list
Step 2 Side & Size:   BUY/SELL toggle > quantity > order type/price
Step 3 Protection:    SL fields > Target fields > Trailing > [Skip]
Step 4 Review:        summary (all fields) > [Place order] > [Back]
```

### 3.3 Information hierarchy — desktop single form
```
1. Symbol search (top, most prominent input)
2. Side/Size/Type/Product/Exchange (grouped fieldset)
3. Protection (inline, not collapsed — room exists, so show it open by
   default with a clear "optional" label, never hidden behind a toggle
   the way mobile's step-skip needs to be)
4. [right column, persistent] Live review panel — mirrors every field
   change in real time, contains the actual [Place order] action
```

### 3.4 Desktop wireframe (≥1024px)
```
┌─────┬──────────────────────────────────────────────────────────────────┐
│ NAV │  Place an order                                                  │
│     │  ┌────────────────────────────────┐  ┌────────────────────────┐ │
│Home │  │ Symbol                          │  │ Review                  │ │
│▓Trade│ │ {Search RELIANCE, NIFTY...___}  │  │                          │ │
│Pos'ns│ │ ┌──────────────────────────┐    │  │  BUY  RELIANCE           │ │
│     │  │ │ 📊 RELIANCE  Reliance Ind│    │  │                          │ │
│─────│  │ │ 📈 NIFTY 24200 CE  17 Jul│    │  │  Qty         1           │ │
│Sess:│  │ └──────────────────────────┘    │  │  Price       Market      │ │
│●PIN │  │                                  │  │  Product     INTRADAY   │ │
│     │  │ [ BUY ▓]  [ SELL ]               │  │  Exchange    NSE         │ │
│     │  │                                  │  │                          │ │
│     │  │ Quantity      Order type         │  │  SL          —           │ │
│     │  │ {1______}     {MARKET ▾}         │  │  Target      —           │ │
│     │  │                                  │  │  Trailing    —           │ │
│     │  │ Product       Exchange           │  │                          │ │
│     │  │ {INTRADAY ▾}  {NSE ▾}            │  │  [    Place order    ]  │ │
│     │  │                                  │  │                          │ │
│     │  │ ── Protection (optional) ──      │  │                          │ │
│     │  │ SL trigger    SL limit            │  │                          │ │
│     │  │ {________}    {________}          │  │                          │ │
│     │  │ Target trigger Target limit       │  │                          │ │
│     │  │ {________}    {________}          │  │                          │ │
│     │  │ Trailing SL (points)               │  │                          │ │
│     │  │ {________}                        │  │                          │ │
│     │  └────────────────────────────────┘  └────────────────────────┘ │
└─────┴──────────────────────────────────────────────────────────────────┘
```

### 3.5 Tablet wireframe (600–1023px)
```
┌──────────────────────────────────────────────┐
│ ≡        Place an order            <Session>  │
├──────────────────────────────────────────────┤
│  Symbol                                        │
│  {Search RELIANCE, NIFTY...______________}     │
│  ┌────────────────────────────────────────┐    │
│  │ result rows                             │    │
│  └────────────────────────────────────────┘    │
│                                                 │
│  [ BUY ▓]  [ SELL ]                             │
│  Quantity          Order type                   │
│  {1______}         {MARKET ▾}                   │
│  Product            Exchange                    │
│  {INTRADAY ▾}       {NSE ▾}                      │
│                                                 │
│  ── Protection (optional) ──                    │
│  SL trigger        SL limit                      │
│  {________}        {________}                   │
│  Target trigger    Target limit                 │
│  {________}        {________}                   │
│  Trailing SL (pts)  {________}                   │
│                                                 │
│  ┌────────────────────────────────────────┐    │
│  │ Review: BUY RELIANCE x1 · Market · NSE  │    │
│  │ [        Place order        ]           │    │
│  └────────────────────────────────────────┘    │
│  ← review is a bottom-anchored persistent bar,  │
│    not a right-column panel (not enough width)  │
└──────────────────────────────────────────────┘
```

### 3.6 Mobile wireframe (≤599px) — the 4-step flow
```
Step 1/4 — Symbol                    Step 2/4 — Side & Size
┌───────────────────────────┐        ┌───────────────────────────┐
│ ← Place an order    1 of 4 │        │ ← Place an order    2 of 4 │
├───────────────────────────┤        ├───────────────────────────┤
│                            │        │  RELIANCE                  │
│ {Search RELIANCE...____} │        │                            │
│                            │        │  [  BUY  ▓]  [  SELL  ]    │
│ 📊 RELIANCE                │        │                            │
│    Reliance Industries      │        │  Quantity                  │
│ 📈 NIFTY 24200 CE           │        │  {1___________________}    │
│    17 Jul expiry            │        │                            │
│                            │        │  Order type                │
│                            │        │  {MARKET ▾}                │
│                            │        │                            │
│                            │        │  Product      Exchange     │
│                            │        │  {INTRADAY▾}  {NSE ▾}      │
├───────────────────────────┤        ├───────────────────────────┤
│                            │        │        [ Continue → ]      │
└───────────────────────────┘        └───────────────────────────┘

Step 3/4 — Protection                Step 4/4 — Review
┌───────────────────────────┐        ┌───────────────────────────┐
│ ← Place an order    3 of 4 │        │ ← Place an order    4 of 4 │
├───────────────────────────┤        ├───────────────────────────┤
│  Buying RELIANCE x1         │        │  Buying RELIANCE x1         │
│                            │        │                            │
│  SL trigger                │        │  Qty          1             │
│  {________}                │        │  Price        Market        │
│  SL limit (optional)        │        │  Product      INTRADAY      │
│  {________}                │        │  Exchange     NSE            │
│                            │        │  SL           ₹2820/2810     │
│  Target trigger             │        │  Target       ₹2950/2950     │
│  {________}                │        │  Trailing     —              │
│  Target limit (optional)    │        │                            │
│  {________}                │        │                            │
│                            │        │                            │
│  Trailing SL (points)       │        │                            │
│  {________}                │        │                            │
│                            │        │                            │
│  [   Skip — no stop   ]     │        │                            │
├───────────────────────────┤        ├───────────────────────────┤
│        [ Continue → ]       │        │   [    Place order    ]    │
└───────────────────────────┘        │   [       Back        ]    │
                                       └───────────────────────────┘
```

### 3.7 User interaction flow
```
Mobile:
  Step 1 → type/pick symbol → auto-advance to Step 2 on pick
  Step 2 → set side/qty/type → [Continue] → Step 3
  Step 3 → fill or [Skip] → Step 4
  Step 4 → [Place order] → inline result on this same screen
           (success: confirmation + [View in Positions →];
            failure: inline Banner, [Back] still available to edit)
  [←] at any step → previous step, all entered values retained

Desktop:
  Fields fill top-to-bottom in the left panel; right panel Review
  updates live on every change (debounced ~150ms on text inputs,
  immediate on selects/toggles). [Place order] lives only in the
  Review panel — pressing Enter in any field does NOT submit, only
  the explicit button does (prevents accidental submission while
  tabbing through fields).
```

### 3.8 Component placement
```
Stepper       — mobile only, owns step state + progress ("2 of 4") + back
Input         — symbol search, quantity, all price/trigger fields
Data Card     — search result rows
Button        — BUY/SELL toggle (segmented control, not two separate
                buttons — visually one control with two states),
                Continue/Place order (primary), Back/Skip (ghost)
Banner        — validation/rejection feedback
Badge         — "AMO" tag when market is closed (shown wherever it's
                currently relevant — Review panel/step 4 — not buried)
```

### 3.9 Empty state
```
Step 1, before typing:
  Empty search box, no result list shown at all (not "type to search"
  placeholder text sitting in a results area — the input's own
  placeholder already says this, per §16 of PRODUCT_DESIGN.md distinguishing
  "haven't typed yet" from "searched, found nothing")

Step 1, typed 1 character (below the "start searching" threshold):
  A single quiet line: "Keep typing to search" — distinct from...

Step 1, searched, no matches:
  "No matching symbols" + the typed query echoed, so the user can see
  what was searched and adjust
```

### 3.10 Loading state
```
Step 1, search in flight:
┌───────────────────────────┐
│ {RELIANCE______________}  │
│ ░░░░░░░░░░░░░░░░░░░░░░░░░░ │   ← skeleton rows, count = previous
│ ░░░░░░░░░░░░░░░░░░░░░░░░░░ │      result count or 3 by default
└───────────────────────────┘

Step 4 / desktop Review, placing order:
  [    Placing order…    ]   ← button-scoped, field area stays
                                 visible and legible beneath/beside it
```

### 3.11 Error state
```
Field-level (e.g. LIMIT selected, no price entered):
  Order type
  {LIMIT ▾}
  Limit price
  {________}  ⚠ Required for LIMIT orders      ← inline, at the field

Request-level (order rejected):
┌───────────────────────────┐
│ ⚠ Symbol 'MADEUP' not found │
│   in NSE EQUITY instruments │
│   [ Edit symbol ]           │
└───────────────────────────┘
  Shown at Review (step 4 mobile / right panel desktop), with a direct
  action back to the relevant step/field rather than a bare message.
```

---

## Page 4 — Positions (`/positions`)

### 4.1 Navigation flow
```
Entry points:  nav "Positions" tap · [Continue to Positions] from Home/Login ·
               [View in Positions →] after placing an order
Exit points:   "…" per-row action → /trade (pre-filled, deep link)
               [Sell] → stays on page, inline result
               [Modify] → bottom sheet/dialog, stays on page
```

### 4.2 Information hierarchy
```
1. Total P&L (largest number on the page, sticky on scroll — desktop
   and mobile both)
2. Connection/live status (directly beside the P&L, always visible)
3. Position list — LTP + P&L per row are visually loudest;
   symbol/exchange/kind are identity, not data, rendered with less
   visual weight than LTP/P&L; qty/avg/protection-status are metadata,
   quietest tier
4. Per-row actions (Sell / Modify / more)
```

### 4.3 Desktop wireframe (≥1024px)
```
┌─────┬──────────────────────────────────────────────────────────────────┐
│ NAV │  Positions                                          [●Live]      │
│     │  ┌──────────────────────────────────────────────────────────┐   │
│Home │  │  Total P&L                                                │   │
│Trade│  │  +₹12,480 ▲                                4 positions    │   │
│▓Pos'ns│ └──────────────────────────────────────────────────────────┘   │
│     │  ═══════════════════════════════════════════════════════════   │  ← sticky
│─────│  Symbol      Exch  Qty   Avg      LTP···    P&L···     Protect  Actions
│Sess:│  ─────────────────────────────────────────────────────────────  │
│●PIN │  RELIANCE    NSE   1     2800.00  2850.00·  +50.00·   SL 2820  [Sell][Mod][…]
│     │  NIFTY24200CE NSE  75    120.50   135.20·   +1102.50· Target   [Sell][Mod][…]
│     │                                                        2950
│     │  TCS (hold)  NSE   5     3500.00  3600.00·  +500.00·  No stop  [Sell][Mod][…]
│     │  INFY (hold) NSE   10    1450.00  1430.00·  -200.00·  No stop  [Sell][Mod][…]
│     │                                                                    │
└─────┴──────────────────────────────────────────────────────────────────┘
Column headers sortable (click to sort, arrow indicates direction).
LTP/P&L columns show the tabular-numeral live value; a brief background
flash (Live Value component) on the specific cell when a tick arrives.
```

### 4.4 Tablet wireframe (600–1023px)
```
┌──────────────────────────────────────────────┐
│ ≡     Positions              [●Live] <Sess>   │
├──────────────────────────────────────────────┤
│  Total P&L                                     │
│  +₹12,480 ▲                    4 positions      │
├──────────────────────────────────────────────┤  ← sticky
│  ┌────────────────────────────────────────┐    │
│  │ RELIANCE  NSE                            │    │
│  │ Qty 1 @ ₹2800.00                          │    │
│  │ LTP ₹2850.00·        P&L +₹50.00·          │    │
│  │ SL ₹2820  ·  Target —                     │    │
│  │ [ Sell ]  [ Modify ]  [ … ]                │    │
│  └────────────────────────────────────────┘    │
│  ┌────────────────────────────────────────┐    │
│  │ NIFTY24200CE  NSE                        │    │
│  │ ...                                       │    │
│  └────────────────────────────────────────┘    │
└──────────────────────────────────────────────┘
Cards, not a table, at this width — a table's column count doesn't
comfortably fit until Expanded, and forcing it here would mean
horizontal scroll, which fights the "scan at a glance" goal.
```

### 4.5 Mobile wireframe (≤599px)
```
┌───────────────────────────┐
│ Positions          <Sess> │
├───────────────────────────┤
│  Total P&L        [●Live] │
│  +₹12,480 ▲                │
│  4 positions                │
├───────────────────────────┤  ← sticky header on scroll
│  ┌───────────────────────┐│
│  │ RELIANCE     NSE  pos  ││
│  │ Qty 1 @ ₹2800.00        ││
│  │                        ││
│  │ LTP        P&L         ││
│  │ ₹2850.00·  +₹50.00·     ││
│  │                        ││
│  │ SL ₹2820                ││
│  │                        ││
│  │ [ Sell ]  [ Modify ] [⋯]││
│  └───────────────────────┘│
│  ┌───────────────────────┐│
│  │ NIFTY24200CE NSE  pos  ││
│  │ ...                    ││
│  └───────────────────────┘│
├───────────────────────────┤
│ [Home][▓Pos][Trade][Sess] │
└───────────────────────────┘
```

### 4.6 User interaction flow
```
Load /positions → PIN prompt (if not already in this session) →
  on 4+ digits entered, auto-connect (kept behavior, single code path
  this time — see PRODUCT_DESIGN §14/interaction guidelines and the
  engineering audit's flagged dual-path bug) → REST fetch for initial
  snapshot → WS connect for live ticks

Tap [Sell] on a row → button becomes "Selling…" (scoped to that row/card
  only) → success: inline confirmation replaces the row's action area
  briefly, then row refreshes/removes from list; failure: inline Banner
  on that row, button re-enabled

Tap [Modify] → bottom sheet opens (existing pattern, kept) with current
  SL/Target pre-filled → [Save] → sheet closes on success, row updates;
  on failure, sheet stays open with inline Banner

Tap [ … ] → navigates to /trade with symbol/exchange/security_id/segment
  pre-filled (existing deep-link behavior, kept)

WS disconnects → connection badge changes state (calm, not alarming),
  all LTP/P&L values begin dimming toward "stale" the moment they exceed
  the staleness window, independent of the reconnect attempt's own timing
```

### 4.7 Component placement
```
Live Value      — LTP cell/value, P&L cell/value (per-position AND the
                  page-level Total P&L)
Data Card       — mobile/tablet position card
(table row)     — desktop rendering of the same Data Card data, via the
                  "same shell, two renderings" rule (§12 PRODUCT_DESIGN)
Badge           — connection status, SL/Target/Trailing tags, "hold" vs
                  "position" kind tag, AMO tag if relevant
Button          — Sell (destructive-outline), Modify (secondary), "…"
                  (ghost, icon-only with accessible label)
Modal/Sheet     — Modify dialog
Banner          — per-row error feedback (sell/modify failures)
```

### 4.8 Empty state
```
┌──────────────────────────────────────────────────┐
│  Total P&L                                        │
│  No open positions                                 │
├──────────────────────────────────────────────────┤
│                                                     │
│              You have no open positions             │
│         Place an order to see it appear here         │
│                                                     │
│              [   Place an order →   ]                │
│                                                     │
└──────────────────────────────────────────────────┘
```

### 4.9 Loading state
```
┌──────────────────────────────────────────────────┐
│  ░░░░░░░░░░░░░░░░░░░░  ░░░░░░░░░░                  │
├──────────────────────────────────────────────────┤
│  ┌────────────────────────────────────────────┐   │
│  │ ░░░░░░░░░░░  ░░░░  ░░░░░                     │   │
│  │ ░░░░░░░░░░░░░░░░░░                            │   │
│  │ ░░░░░░░  ░░░░░░░                               │   │
│  │ [░░░░░░]  [░░░░░░░░]  [░░]                      │   │
│  └────────────────────────────────────────────┘   │
│  (× 3 skeleton rows/cards while the initial fetch  │
│  is in flight; WS "connecting" badge shown          │
│  simultaneously, independent of the REST fetch)     │
└──────────────────────────────────────────────────┘
```

### 4.10 Error state
```
Initial fetch fails entirely:
┌──────────────────────────────────────────────────┐
│  ⚠ Couldn't load your positions                    │
│    [ Retry ]                                       │
└──────────────────────────────────────────────────┘
  (Whole-page error only when there is genuinely no data to show at
  all — once any position data has loaded successfully once, a later
  failure degrades to the connection-status badge changing state,
  never wipes already-visible positions off the screen.)

Per-row action fails (Sell/Modify):
  Inline Banner scoped to that specific row/card, per §4.6 — never a
  page-level error for a single row's action failure.
```

---

## Cross-Page Consistency Checklist

(Every item below must hold true across all four pages simultaneously — this is the test for whether "one unified design language" actually succeeded, not just an intention.)

- [ ] Nav Rail/Tab Bar renders identically (same 4 items, same order, same current-page indication logic) on every page, every breakpoint.
- [ ] Every numeric value on every page uses a Data-* type role + tabular figures — verified page by page: Home's P&L, Login's (none — correct, it has no data), Trade's Review panel numbers, Positions' entire table/card set.
- [ ] Every primary action button uses identical padding/radius/weight across pages (Sign in, Continue to Positions, Place order, Sell — visually one button language, four different labels).
- [ ] Every Banner (success/error/info) across all 4 pages shares one visual shell.
- [ ] Every skeleton loading state matches its final content's shape, on all 4 pages.
- [ ] Focus-visible ring identical everywhere.
- [ ] Dark/light theme parity checked per page — no page (unlike today's home.html/login.html) is dark-only.

---

## Visual Mood Board

*(Descriptive — actual swatches, exact type specimens, and hi-fi comps are a separate visual-exploration deliverable once this structural direction is approved; this section describes the target feeling precisely enough to brief that exploration, per the open question left in PRODUCT_DESIGN.md about the accent color.)*

### Overall aesthetic
Quiet, confident, fast. The visual target sits at the intersection of a well-made financial instrument and a well-made productivity tool — closer to a cockpit instrument panel than a retail app. Nothing shouts. Every element has clearly earned its place on screen because it carries information a trader needs, not because it decorates. The product should feel *expensive through restraint* — the way a well-made watch face communicates precision through what it leaves out, not through ornamentation.

### Typography
A humanist UI sans (think the general family of Inter/SF Pro/Söhne — precise, slightly warm, excellent at small sizes) for language; a true tabular monospace (think the family of JetBrains Mono/SF Mono/Berkeley Mono) exclusively for numbers, IDs, and timestamps. The contrast between the two typefaces *is* an information signal — a user should be able to tell "this is a number I should trust and compare" from "this is a label explaining it" by typeface alone, before even reading. Headlines are confident but never oversized — the biggest text on any screen is a live P&L number, never a marketing headline (Home's hero, in this system, is smaller and quieter than a positions page's total).

### Spacing
Generous on mobile (comfortable density, per §6 PRODUCT_DESIGN), tightened deliberately on desktop data surfaces (compact density) — but the tightening only ever removes air between *related* things (rows in a table, fields in a group); it never removes the breathing room around a page's primary number or its primary action. Nothing ever feels cramped near the one thing you're meant to look at first.

### Icons
Minimal, functional, never illustrative. A small, consistent icon set used only where an icon adds unambiguous meaning faster than a word would (▲/▼ for direction, a connection dot for live/stale, a lock glyph for the security note) — never a full icon library scattered decoratively (no icon-per-menu-item just to fill space, no icon-per-feature-card the way the current home.html uses colored dots per list item mostly for decoration rather than meaning). Where an icon is icon-only (no visible label), it always carries an accessible name — a rule, not a suggestion, per the accessibility section.

### Shadows
Elevation is felt, not seen — very low-opacity, tight-radius shadows that read as "this surface is slightly raised" without ever producing a visible dark smear (the failure mode of the current design's `--shadow: 0 1px 2px rgba(16,24,40,.04), 0 1px 3px rgba(16,24,40,.06)`, which is actually already close to correct and should be the *starting point*, refined rather than replaced). Dark theme uses shadows even more sparingly — on near-black surfaces, elevation is communicated primarily through a subtle border/surface-color shift, with shadow as a secondary, barely-perceptible reinforcement, since large dark shadows on dark backgrounds tend to just look like nothing happened.

### Motion
Fast, purposeful, quiet — every motion described in §13 of PRODUCT_DESIGN.md (Orientation/Feedback/Continuity/Absence-handling), nothing beyond those four categories. The one moment motion is allowed to be *felt* rather than merely functional is a live tick updating a price/P&L — a brief, soft luminance shift, gone in well under half a second, that makes the product feel alive without ever feeling like a notification demanding attention. Nothing bounces, nothing overshoots its target, nothing spins longer than it takes to actually load.

### Component style
Flat surfaces, 1px hairline borders (not heavy strokes, not borderless-floating-on-shadow-alone), consistent corner radius across every component at a given size tier (small controls slightly less rounded than cards, cards less rounded than modals — a radius hierarchy, not one fixed value everywhere, mirroring how Linear/Stripe/Apple all scale radius with size rather than using a single constant). Buttons are text-first (a label is never optional on a primary action) with icons only as reinforcement, never as replacement, for anything that isn't purely navigational chrome.

### The one-sentence test
If you removed every logo and every piece of copy from a screenshot of this product, a trader should still be able to tell, from layout and type alone, "this was designed by people who trade, for people who trade" — not "this was designed by people who build developer tools, and traders are welcome to use it too."

---

## Open items before implementation

1. Confirms/overturns the four defaults stated at the top of this document — same four questions as `PRODUCT_DESIGN.md`, now with a concrete layout attached to each so they're easier to react to.
2. The accent-color exploration (actual swatches, not description) is the natural next deliverable once this structural direction is signed off — flag if you'd rather see that in parallel rather than strictly after.
3. Any page/breakpoint combination above that reads wrong for how you actually expect to use this day-to-day (e.g. if desktop is rarely your context, the desktop wireframes matter less than getting mobile exactly right, and vice versa).

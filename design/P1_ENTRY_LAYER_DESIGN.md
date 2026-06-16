# MyInvest User Entry Layer Design Document (P1-ENTRY-1)

## 1. Objective

Build a User Entry Layer for MyInvest system that converts current analytical system into a usable product interface.

Goal:
- Users can understand "what to do next"
- Users can navigate without technical knowledge
- System provides guided workflow instead of raw dashboards

---

## 2. Current Problem

Current system status:
- All backend engines complete (P0-P2)
- Dashboard exists but is data-centric
- No entry guidance or workflow orchestration
- Users must manually choose pages

Result:
- High cognitive load
- No clear starting point
- No guided decision flow

---

## 3. Target Architecture

Introduce a new layer:

P1-ENTRY LAYER (User Entry System)

Sits above:
- dashboard
- risk system
- macro system
- research system
- report system

---

## 4. Core Components

### 4.1 Entry Homepage (/home)

Purpose:
Single entry point for all users.

Must display:

1. Market Status Card
- overall_market_state
- liquidity_index
- risk_level

2. Main Theme Card
- current_theme
- strength_score
- leading_symbols

3. Portfolio Summary Card
- shadow return
- benchmark return
- drawdown

4. Risk Snapshot Card
- overall_risk_score
- exposure_warning

5. Next Action Suggestion (CRITICAL)
- recommended_next_view
- reasoning

---

### 4.1.1 Human Entry Homepage (/home_human)

Purpose:
Derived plain-language entry page for non-engineering users.

Rules:
- Reads the same state as /home
- Translates market, theme, risk, portfolio, next_action, and navigation_plan into human-readable language
- Does not add analysis logic
- Does not change JSON schema
- Does not write SQLite
- Does not change replay, event_log, shadow engine, risk, macro, comparison, or research systems
- Does not expose trading controls or sensitive account fields

---

### 4.2 Guided Navigation Engine

A rule-based routing layer:

Input:
- portfolio state
- risk state
- macro state
- research state

Output:
- next_best_view

Examples:
- High risk → /risk
- Strong trend → /comparison
- Weak theme clarity → /research
- Stable market → /portfolio

---

### 4.3 Workflow Path System

Defines a default user journey:

Path A (Normal Market):
/home → /market → /research → /portfolio → /report

Path B (High Risk):
/home → /risk → /portfolio → /comparison

Path C (Volatile Market):
/home → /macro → /risk → /comparison

---

### 4.4 Navigation Header System

All pages must include:

- Home shortcut
- Risk shortcut
- Portfolio shortcut
- Research shortcut
- Report shortcut

---

## 5. Data Requirements

Entry layer MUST consume:

- /system/dashboard_state
- /risk/state
- /macro/state
- /comparison/state
- /portfolio/state
- /research/latest

No new backend logic allowed.

---

## 6. UI Principles

- No raw data dumps
- Every page must answer:
  "What should I do next?"
- Reduce cognitive load
- Prioritize guidance over data

---

## 7. API Additions (Read-only only)

Add:

GET /entry/home_state
GET /home_human

Returns:
- market summary
- theme summary
- risk summary
- portfolio summary
- next_action
- plain-language human entry view

---

## 8. Constraints

STRICT:
- No trading logic
- No write operations
- No schema changes to core system
- No modification to replay/event_log/shadow engine
- JSON remains source of truth

---

## 9. Success Criteria

System is successful when:

- User can enter /home and understand system state in <10 seconds
- User can follow recommended navigation without guessing
- No page requires technical knowledge to interpret
- Entry layer becomes primary access point

---

## 10. Output Definition

Entry layer outputs:

- entry_home_state.json
- next_action.json
- navigation_plan.json
- /home_human derived HTML view

---

END OF SPEC

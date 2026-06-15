
# CODEx EXECUTION GUIDE (SIMPLIFIED)

## Goal
Build a production-ready investment research + portfolio simulation system with:
- strict JSON-first pipeline
- SQLite read model
- history replay capability (lightweight version)

---

## CORE RULES

### 1. JSON ONLY INPUT/OUTPUT (STRICT)
All AI/service outputs must be JSON:
- analysis
- decision
- risk
- metadata

No free-form markdown in backend logic.

---

### 2. SEPARATE 3 CONCEPTS

#### (A) Research
- Understand market / stock
- No execution meaning

#### (B) Decision
- Buy / sell / hold suggestion
- Must be explicitly recorded

#### (C) Execution (Shadow only)
- Paper trading simulation only
- Never mix with research

---

### 3. HISTORY MUST BE APPENDED, NOT OVERWRITTEN
All important objects are append-only:

- market snapshot
- research snapshot
- decision record
- portfolio snapshot

---

### 4. MINIMAL EVENT MODEL (LIGHT VERSION)

Each change should produce:

{
  "timestamp": "...",
  "type": "market | research | decision | portfolio",
  "payload": {}
}

No need full event sourcing engine yet.

---

## CODEx TASK STRATEGY

Work in this order:

1. Enforce JSON schema validation gate
2. Standardize research output format
3. Separate decision model
4. Implement append-only history tables (SQLite)
5. Add shadow portfolio replay
6. Add timeline query API

---

## SUCCESS CRITERIA

- Any decision can be traced back to:
  data → research → decision → portfolio change
- System can replay last 30 days state
- No mixed-format outputs in backend

---

## IMPORTANT

Do NOT over-engineer:
- No distributed systems
- No microservices
- No external infra

Keep everything local + SQLite + Python + FastAPI

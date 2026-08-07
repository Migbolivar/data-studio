# Data Studio — Insight Engine

AI-powered data analysis platform: upload CSV/Excel → dynamic KPIs of the active filter → LLM analysis with **3 insights + conclusion + recommendation** — grounded in real computed metrics (no hallucination).

**Live demo:** https://finance.bmops.tech (AI Finance Advisor)

## Why it matters
Most "AI analytics" tools let the LLM guess. This one **computes metrics with Pandas first**, then the LLM only *translates* those real numbers into insights — with a hard rule: every insight must cite a concrete computed value.

## Stack
- **Pandas** — metric computation (KPIs of the active filter, trends, anomalies)
- **Insight Engine** — `insight_engine.py`:
  - `_detect_data_type()` → financial / quantitative / qualitative (encuestas, feedback)
  - `qualitative_insights()` → frequencies, mode, top-5, missing-data %
  - `generate_insights()` → metrics + anomaly detection
- **Chart.js** — visualizations
- **LLM** — interprets computed metrics only (prompt enforces citing real numbers)

## Pipeline
```
CSV/Excel → Pandas metrics (real numbers) → LLM interpretation → 3 insights + conclusion + recommendation
```

## Files
- `insight_engine.py` — the core engine (data type detection + qualitative + financial analysis)
- `server.py` — stateless HTTP backend with PIN auth (HMAC cookie)
- `index.html` — frontend (upload, filters, charts, AI analysis)

## Role
Designed and built the full pipeline: the rule that *"Pandas computes, the LLM only translates"* is the product's core differentiator.

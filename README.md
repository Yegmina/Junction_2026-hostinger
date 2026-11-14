# Unicorn Oracle: Make Unicorns Real (Junction 2026, Cala challenge)

Sourced fundraising foresight for first-time founders. Describe your startup and target round, and Unicorn Oracle:

1. **Pulls evidence from Cala**: competitors, recent funding rounds in your sector and region, and investors who still lead rounds at your stage. Each fact gets an id (`E1`, `E2`...) and keeps its Cala sources.
2. **Extracts drivers**: the forces that decide your round, tagged by PESTEL, with impact, uncertainty and the evidence behind them.
3. **Builds a 2x2 scenario matrix** from the two highest-impact, most uncertain drivers, with signposts to watch.
4. **Estimates the chance your round closes**: `P(round) = Σ P(scenario) × P(round | scenario)`, with a band showing the spread across scenarios.
5. **Runs an AI investment committee** (bull partner, risk partner, sector specialist) and shortlists lead investors. Only investors that actually appear in the Cala evidence are kept, so no invented names.

Every claim in the UI has clickable evidence chips that jump to the source fact.

## How Cala is used

| Cala feature | Endpoint | What it gives the founder |
|---|---|---|
| Natural-language answers with sourced context | `POST /v1/knowledge/search` | Competitors, recent rounds and active lead investors; every fact keeps its source documents |
| Structured query (Cala QL) | `POST /v1/knowledge/query` | Top-funded companies in the sector with rounds and investors |
| Entity mentions | `entities` in search answers | Exact graph ids for the competitors Cala found |
| Entity search + introspection | `GET /v1/entities`, `GET /v1/entities/{id}/introspection` | Resolve each shortlisted investor to its graph entity and check which relationships exist |
| Graph traversal | `POST /v1/entities/{id}` | `INVESTED_IN` edges into competitors (who backs them), each investor's portfolio, and `PARTICIPATES_IN_FUNDING_ROUND` → round `announcement_date` to prove they are still active |

From this the app flags **conflicts of interest** (an investor that backs a direct competitor, from the graph or sourced text), marks each lead **Verified in Cala graph** with portfolio size and latest deal date, and ranks conflict-free, verified leads first.

## Example replays

The three examples on the landing page replay real recorded runs (Cala + LLM), compressed to about 9 seconds, so demos are reliable. Editing any field runs the live pipeline. Re-record with:

```bash
cd backend && set -a && . ../.env && set +a && .venv/bin/python -m scripts.record_examples
```

## Where it comes from

- **ORACLE** (Metropolia foresight platform): drivers, PESTEL tagging, scenario matrix workflow and multi-agent debate. Ideas are reimplemented here; no ORACLE code is copied.
- **Q-FIN** (QuantumFinances): scenario probabilities and event-probability scoring, the FastAPI + Vue + Docker shape. The quantum part is dropped.
- **Cala** is the evidence layer: nothing is analysed that did not come from Cala.

## Run with Docker

```bash
cp .env.example .env   # add CALA_API_KEY and GEMINI_API_KEY (or OPENAI_API_KEY)
docker compose up --build
```

Open http://localhost:8080.

Without keys the app still runs in clearly labelled **demo mode** with fictional companies and investors.

Get a Cala key at https://console.cala.ai/api-keys. Junction teams can redeem the promo code from the challenge page under Billing → Extra credits.

## Run locally

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
set -a; . ../.env; set +a      # optional: load keys
.venv/bin/uvicorn app.main:app --port 8000 --reload

cd ../frontend
npm install
npm run dev                    # http://127.0.0.1:5173, proxies /api to :8000
```

## Tests

```bash
cd backend && .venv/bin/python -m pytest -q
```

## API

- `GET /api/health` returns `{"dataMode": "cala"|"demo", "analysisMode": "openai"|"gemini"|"demo"}`.
- `POST /api/analyze` takes a startup profile (`name`, `description`, `sector`, `country`, `stage`, `targetAmountEur`, `horizonMonths`). It streams server-sent events of these types: `start`, `status`, `evidence`, `plan`, `committee`, `done` and `error`.

## Safety for a public demo

- Requests are rate-limited per IP (`RATE_LIMIT_PER_HOUR`).
- Users cannot pass URLs to the server.
- Inputs are length-limited.
- CORS is restricted to configured origins.
- Upstream error bodies are logged, not shown to users.

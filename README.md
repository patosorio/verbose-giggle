# Junket

Collaborative trip planning for groups who can't agree on where to stay.

Junket turns a group trip into a shared, structured plan instead of a scattered
WhatsApp thread of screenshots and half-decided dates. One person builds the
skeleton — legs, dates, party size, budget — and the app researches real flights,
real hotels, and real local activities for each leg, then the group reacts and
one person locks in the final picks.

## The problem

Planning a multi-stop group trip usually means one person doing all the research
manually, pasting options into a chat, and losing track of who agreed to what.
Junket replaces that with a single source of truth per trip: every leg gets
priced, sourced options in three tiers, the group can react to each one, and an
organizer locks the final choice — with a running budget that updates as legs
get locked.

## What it does

- **Multi-leg trip building** — a short wizard captures route, dates, party
size (adults/children), and a budget band per leg.
- **Real flight and hotel search** — priced, bookable options fetched live per
leg, tiered into Budget / Comfort / Premium, each traceable back to the exact
API response that produced it.
- **AI-researched activities, never unsourced** — local activity suggestions
come from an LLM research pass, but every single suggestion is required to
carry at least one citation before it's allowed to reach the database. No
citation, no suggestion — enforced at the schema level, not a guideline.
- **Group reactions, organizer-gated locking** — everyone in the trip can react
to options; only the trip organizer can lock one in per leg, and every
lock/unlock is audited.
- **Running budget, no surprises** — the sidebar budget tracker sums locked
option prices against the trip's target as legs get finalized.
- **Magic-link auth** — no passwords to manage for a group of family and
friends who'll use this a handful of times a year.

Built and tested against a real 5-leg reference itinerary (Bangkok → Phuket →
Koh Yao Noi → Koh Lanta → Krabi → Bangkok, 6 adults + 1 child) rather than
synthetic test data.

## Architecture highlights

- **Deterministic where the data is deterministic.** Flight and hotel search
and pricing are plain async API calls against SerpApi — no LLM anywhere near
a price or a booking link.
- **AI only where research genuinely requires it.** Activities are the one
option type that benefits from open-ended research, so that's the one path
that uses an LLM — a two-call pattern (research, then a schema-forced
extraction call) rather than an open-ended agent loop.
- **No agent framework.** Orchestration is a single `asyncio.gather` fanning
out to the flight, hotel, and activity fetchers per leg — plain Python, not
LangChain/LangGraph. There's no durable workflow state to manage that a
database write after each run doesn't already cover.
- **Traceability by construction.** Every priced option carries a foreign key
to the raw API response it came from, written before any derived row exists.
Nothing is ever priced or claimed without a receipt.
- **Docs-first.** Architecture, data model, API contracts, and a phased build
plan were written and reviewed before any application code, with each
phase's exit criteria checked against the real reference itinerary.

## Tech stack

**Backend** — FastAPI (async), Pydantic v2, SQLAlchemy 2.0 (async) + asyncpg,
Alembic, PostgreSQL (with `citext` for case-insensitive email handling).

**AI** — Anthropic Claude API, direct tool-use calls (`web_search` +
schema-forced extraction) — no orchestration framework.

**Data sourcing** — SerpApi (Google Flights / Google Hotels engines).

**Frontend** — Next.js 16 (App Router), Tailwind CSS v4, ShadCN/UI (Base UI),
TanStack Query, React Hook Form + Zod.

**Infra** — Docker, Cloud Run, Cloud SQL, Secret Manager, Cloud Tasks, Cloud
Build for the API; Vercel for the frontend.

**Tooling** — `uv` (dependency + environment management), Ruff, mypy (strict),
pytest / pytest-asyncio; `pnpm` for the client.

## Running locally

### API

```bash
git clone <repo-url>
cd travelagency

# API environment (see api/.env.example for the full list)
cp api/.env.example api/.env
# fill in DATABASE_URL, JWT_SIGNING_KEY, and any provider keys you're testing against

docker compose up -d --build
```

This brings up the API (`api-1`) and Postgres (`db-1`) as containers. Apply
migrations once the database is up:

```bash
cd api
uv run alembic upgrade head
```

The API is then live at `http://localhost:8000`, with interactive docs at
`http://localhost:8000/docs`.

Run the test suite:

```bash
uv run pytest
```

### Frontend

```bash
cd client
cp .env.example .env.local
# NEXT_PUBLIC_API_BASE_URL should point at the API (default http://localhost:8000)

pnpm install
pnpm dev
```

The app is then at `http://localhost:3000`. Auth is magic-link: request a link,
open the verify URL (console email provider prints it locally), then use the
trips / wizard / leg review UI against the running API.

## Project structure

```
travelagency/
├── api/
│   ├── main.py              # FastAPI app entrypoint
│   ├── core/                # config, security, logging, error handling
│   ├── db/                  # SQLAlchemy models, session, Alembic migrations
│   ├── schemas/             # Pydantic request/response models
│   ├── routers/             # HTTP layer — parses requests, calls services
│   ├── services/            # domain logic, all DB writes
│   ├── research/            # SerpApi + Claude research clients
│   ├── worker/              # background research-run consumer
│   └── tests/
├── client/                  # Next.js App Router frontend
│   ├── app/                 # routes — (auth), (app)/trips, wizard, legs
│   ├── components/          # UI by domain + ShadCN primitives
│   ├── hooks/               # TanStack Query hooks
│   └── lib/                 # api client, auth context, types
├── docker-compose.yml
└── cloudbuild.yaml
```

## Status

- [x] Foundations — async FastAPI skeleton, Postgres, Alembic wired
- [x] Schema — trips, members, travelers, legs, magic-link auth end to end
- [x] Trip / traveler / leg CRUD
- [x] Deterministic flight + hotel search (SerpApi)
- [x] Activities research agent + citation-enforcement eval suite
- [x] Research orchestration across a full trip
- [x] Core API surface (reactions, locks, budget, sources/citations)
- [x] Frontend (trips shell, wizard, leg review, budget, magic-link auth)
- [ ] Deployment hardening (Cloud Run worker, Vercel prod wiring)

## License

MIT

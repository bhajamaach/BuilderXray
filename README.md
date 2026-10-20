# BuilderXray

A small FastAPI service that serves a statically exported Next.js app and runs cited public-record checks.

## Local development

1. Copy `.env.example` to `.env`; you can also connect TinyFish from **Connections** in the local UI. The key is written to `.env` on the FastAPI server and is never returned to the browser. `LIVE_PASSCODE` is required for remote live runs; local runs use the configured key directly.
2. Build the frontend: `cd frontend && npm ci && npm run build`.
3. Start the API and static frontend: `cd backend && uvicorn app.main:app --reload --port 8000`.
4. For frontend hot reload, use `cd frontend && npm run dev` in another terminal. The development Next config proxies `/api` to port 8000.

Without a TinyFish key, checks use saved reports. Set `DEMO_MODE=replay` to always use fixtures. The local `.env` is ignored by Git and Docker. The in-app key editor is restricted to localhost and is intended for a single local operator, not multi-user accounts.

## Container deployment

Build with `docker build -t builderxray .` and run with `docker run -p 8000:8000 --env-file .env builderxray`. The service listens on `$PORT` when supplied by the host. Deploy the single container on Render, Railway, or Fly.io and configure its environment variables there.

## Current source coverage

- TinyFish Search is integrated. News results remain partial until Claude classification and page validation are configured.
- TinyFish Search and Fetch find and read official Haryana RERA project pages directly, without waiting on an interactive browser agent. Results are restricted to the selected state's official portal and checked against the query. Delhi RERA may remain unavailable where the portal cannot be reached through TinyFish; that produces an unknown verdict rather than a clean result.
- MCA company/LLP Master Data and eCourts are linked for manual checks because both name-search flows require CAPTCHA completion. BuilderXray does not bypass CAPTCHA or claim an automated result for either source.
- eCourts party-name searches remain manual because the official search requires a court jurisdiction, registration year, and CAPTCHA. Reports link directly to the official search page.

Saved fixtures are dated examples from public Haryana RERA records. Each fixture claim includes a direct source URL. Saved reports do not represent a live check.

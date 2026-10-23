# Notes for coding agents

- **Installing or setting up PaperManager for a user** (install, deploy, run it locally, "set it
  up for me"): follow [DEPLOY.md](DEPLOY.md) step by step. It is an interview-driven runbook:
  ask the questions, write `.env`, start `docker-compose.selfhost.yml` and run
  `scripts/check_setup.py`.
- **Working on the code:** developer context lives in [.specs/](.specs/), starting with
  [.specs/000_general.md](.specs/000_general.md). Tests: `cd backend && pytest`, and
  `cd frontend && npm test`.
- Never commit `.env`, `docker-compose.yml`, `backend/credentials.json` or `backend/token.json`.

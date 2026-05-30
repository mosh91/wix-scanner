# Storage Model (Postgres vs SQLite)

This document explains why this project currently uses both Postgres and SQLite.

## Short answer

- Postgres is the canonical primary database for the platform schema and production-grade relational data model.
- SQLite is currently used in some service modules for local operational stores, fast bootstrap persistence, and deterministic testability.

## Where this is visible in the repo

- Postgres is part of the default stack in [infra/wix_scanner/docker-compose.yml](../infra/wix_scanner/docker-compose.yml) and initialized from [docs/DB_SCHEMA.sql](./DB_SCHEMA.sql).
- Some backend services initialize local SQLite files from env paths, for example:
  - credential lifecycle service in [backend/app/services/credential_lifecycle.py](../backend/app/services/credential_lifecycle.py)
  - site-event binding service in [backend/app/services/site_event_binding.py](../backend/app/services/site_event_binding.py)
- Current backend env defaults point to local db files in [backend/.env.example](../backend/.env.example).

## Why this was done

- Story-driven delivery favored shipping Phase 1 reliability and Wix integration behavior first.
- SQLite gave simple, isolated persistence for features like lifecycle/audit state and reduced migration overhead during MVP iterations.
- The project still keeps Postgres as the long-term primary data model target and runtime dependency.

## Practical guidance today

- For local development and current tests: SQLite-backed service files are expected and supported.
- For production hardening: consolidate these service-local SQLite stores into Postgres-backed tables/migrations as part of later-phase hardening.

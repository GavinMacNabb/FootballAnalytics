# Issue Implementation Map

This document maps the current backend database work to the GitHub issues that
define the project direction.

## #2 Data model

Issue: <https://github.com/GavinMacNabb/FootballAnalytics/issues/2>

Implemented by:

- `schema/core_football_schema.json`
- `docs/core-football-schema.md`
- the canonical `football` schema created by `football-db init-schema`

The model defines teams, players, games, events and stats. Coaching data is
intentionally excluded and handled by separate coaching-data issues.

## #5 Store data

Issue: <https://github.com/GavinMacNabb/FootballAnalytics/issues/5>

Implemented by:

- Terraform-managed local Postgres in `infra/postgres`
- `football-db up` / `football-db down`
- persistent Docker volume `football-analytics-postgres-data`
- normalized model tables in the `football` schema
- source-preserving staging tables in the `nflverse` schema

The database is queryable directly through Postgres and can be rebuilt from
stored nflverse release assets.

## #6 Update data

Issue: <https://github.com/GavinMacNabb/FootballAnalytics/issues/6>

Implemented foundation:

- `nflverse download-samples` tracks release asset metadata and local checksums.
- `nflverse load-samples` imports changed data with upserts.
- `nflverse test-reimport` verifies that reimporting does not duplicate rows.
- `football-db build-model` syncs canonical model tables after staging updates.
- `nflverse sync-samples` checks release metadata and downloads only changed or
  missing selected assets.
- `nflverse sync-samples --load` reimports changed assets and records refresh
  audits in PostgreSQL.

Future work should add scheduled refresh orchestration around these commands.

## #11 Define core football schema from parquet data

Issue: <https://github.com/GavinMacNabb/FootballAnalytics/issues/11>

Implemented by:

- `schema/core_football_schema.json` for machine-readable table grains, primary
  keys, source mappings, relationships and exclusions.
- `docs/core-football-schema.md` for human-readable schema guidance.
- database validation covering source and model relationships.
- sample validation against downloaded nflverse Parquet release assets.

## Command Flow

Local backend setup:

```sh
uv run --python 3.12 football-db up --auto-approve
uv run --python 3.12 football-db init-schema
uv run --python 3.12 nflverse download-samples
uv run --python 3.12 nflverse load-samples
uv run --python 3.12 football-db check
```

Refresh after assets change:

```sh
uv run --python 3.12 nflverse sync-samples --load
uv run --python 3.12 football-db check
```

# Core Football Schema

Issue refs: [#2](https://github.com/GavinMacNabb/FootballAnalytics/issues/2),
[#5](https://github.com/GavinMacNabb/FootballAnalytics/issues/5),
[#11](https://github.com/GavinMacNabb/FootballAnalytics/issues/11).

The backend database now has two layers:

- `nflverse`: source-preserving staging tables loaded from nflverse release
  assets.
- `football`: canonical dimensions, facts and ID crosswalks for NFL analytics
  models.

Coaches, coach assignments and play-caller data are intentionally excluded from
this schema slice. They belong to the separate coaching-data issue.

## Contract

The machine-readable contract lives at
[`schema/core_football_schema.json`](../schema/core_football_schema.json).

It documents table grains, primary keys, source asset mappings, required
columns, core relationships and first-build exclusions.

## Canonical Tables

| Table | Grain | Source |
| --- | --- | --- |
| `football.dim_teams` | One row per team abbreviation. | `teams_colors_logos.parquet` |
| `football.dim_players` | One row per GSIS player ID. | `players.parquet` plus weekly roster supplements |
| `football.xref_player_ids` | One row per provider/player ID. | `players.parquet`, weekly rosters, deterministic snap mapping |
| `football.fact_games` | One row per game. | `games.parquet` |
| `football.fact_events` | One row per game/play. | `play_by_play_2024.parquet` |
| `football.fact_player_team_weeks` | One row per player/team/week roster assignment. | `roster_weekly_2024.parquet` |
| `football.fact_player_week_stats` | One row per player/team/week stats record. | `stats_player_week_2024.parquet` |
| `football.fact_team_week_stats` | One row per team/week stats record. | `stats_team_week_2024.parquet` |
| `football.fact_snap_counts` | One row per game/player/team snap-count record. | `snap_counts_2024.parquet` |

## Commands

Load source assets and build canonical model tables:

```sh
uv run --python 3.12 nflverse download-samples
uv run --python 3.12 nflverse load-samples
```

Sync canonical tables again after staging data already exists:

```sh
uv run --python 3.12 nflverse build-model-tables
```

Validate relationships and idempotency:

```sh
uv run --python 3.12 nflverse validate
uv run --python 3.12 nflverse test-reimport
```

## Validation Coverage

Validation checks source and model relationships:

- Schedule teams resolve to `nflverse.teams` and `football.dim_teams`.
- Weekly roster teams resolve to team dimensions.
- Player weekly stats resolve to player and team dimensions.
- PBP events resolve to games.
- Snap counts resolve to games, teams and player IDs through PFR-to-GSIS
  mappings.
- Reimporting the same sample assets does not duplicate records.

## Verification Run

Verified on 2026-09-30 against a temporary local PostgreSQL database.

`nflverse load-samples` populated the canonical schema with these row counts:

| Table | Rows |
| --- | ---: |
| `football.dim_teams` | 36 |
| `football.dim_players` | 25,036 |
| `football.xref_player_ids` | 70,307 |
| `football.fact_games` | 7,548 |
| `football.fact_events` | 10,000 |
| `football.fact_player_team_weeks` | 46,572 |
| `football.fact_player_week_stats` | 9,991 |
| `football.fact_team_week_stats` | 570 |
| `football.fact_snap_counts` | 10,000 |

All staging and model relationship checks returned zero failures.
`nflverse test-reimport` returned identical before/after row counts and
`reimport_idempotent: true`.

## Modeling Notes

Use `football` tables for model features, predictions and dashboards. Keep the
`nflverse` staging tables for source auditing, troubleshooting and future
reimport comparisons.

The first build intentionally preserves a narrow but extensible schema. As model
features mature, add new nullable columns or child facts rather than mutating
source IDs or changing table grains.

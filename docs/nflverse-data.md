# nflverse Data Feed

## Provider decision

Use [nflverse/nflverse-data](https://github.com/nflverse/nflverse-data) as the
primary football data provider.

This is a post-game batch feed. Download GitHub release assets directly. Do not
use repository source-code ZIP archives as data inputs.

## Selected releases

| Release tag | Use | First-build sample asset |
| --- | --- | --- |
| [`pbp`](https://github.com/nflverse/nflverse-data/releases/tag/pbp) | Play-by-play data for game breakdowns and custom analytics. | [`play_by_play_2024.parquet`](https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_2024.parquet) |
| [`schedules`](https://github.com/nflverse/nflverse-data/releases/tag/schedules) | Game IDs, seasons, weeks, dates, matchups and results. | [`games.parquet`](https://github.com/nflverse/nflverse-data/releases/download/schedules/games.parquet) |
| [`stats_player`](https://github.com/nflverse/nflverse-data/releases/tag/stats_player) | Player statistics. Start with weekly files. | [`stats_player_week_2024.parquet`](https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2024.parquet) |
| [`stats_team`](https://github.com/nflverse/nflverse-data/releases/tag/stats_team) | Team statistics. Start with weekly files. | [`stats_team_week_2024.parquet`](https://github.com/nflverse/nflverse-data/releases/download/stats_team/stats_team_week_2024.parquet) |
| [`players`](https://github.com/nflverse/nflverse-data/releases/tag/players) | Player IDs, names, biographical information and cross-source ID mappings. | [`players.parquet`](https://github.com/nflverse/nflverse-data/releases/download/players/players.parquet) |
| [`teams`](https://github.com/nflverse/nflverse-data/releases/tag/teams) | Team IDs, abbreviations, names, colours and logo URLs. | [`teams_colors_logos.parquet`](https://github.com/nflverse/nflverse-data/releases/download/teams/teams_colors_logos.parquet) |
| [`weekly_rosters`](https://github.com/nflverse/nflverse-data/releases/tag/weekly_rosters) | Player-to-team assignments by season and week. | [`roster_weekly_2024.parquet`](https://github.com/nflverse/nflverse-data/releases/download/weekly_rosters/roster_weekly_2024.parquet) |
| [`snap_counts`](https://github.com/nflverse/nflverse-data/releases/tag/snap_counts) | Player usage on offense, defense and special teams by game. | [`snap_counts_2024.parquet`](https://github.com/nflverse/nflverse-data/releases/download/snap_counts/snap_counts_2024.parquet) |

Advanced charting, contracts, draft data, injuries, depth charts, NGS and other
releases are outside the first build.

## Download and storage policy

Prefer Parquet files. Use CSV only when needed for inspection.

The downloader writes original files to `data/raw/nflverse/<release-tag>/`.
`data/raw/nflverse/manifest.json` records:

- release tag
- release asset ID
- asset name
- source updated timestamp
- source digest when GitHub provides one
- source size
- browser download URL
- local SHA-256 checksum

Refresh logic must compare asset timestamps/checksums, not just release tags.
When an asset changes, reimport it with upserts so existing records are updated
without duplicate rows.

## PostgreSQL import

The sample loader creates a `nflverse` schema with focused relational tables:

- `asset_imports`
- `teams`
- `games`
- `players`
- `player_id_mappings`
- `weekly_rosters`
- `player_stats_weekly`
- `team_stats_weekly`
- `pbp`
- `snap_counts`

Source IDs are preserved. Cross-source player IDs from `players.parquet` are
stored in `player_id_mappings`; this supports joins such as snap-count PFR IDs
back to GSIS player IDs.

The loader also syncs model-ready canonical tables into the `football` schema.
See [Core Football Schema](core-football-schema.md) for the model table grains,
primary keys and source mappings.

Run:

```sh
docker compose up -d postgres
uv run --python 3.12 nflverse download-samples
uv run --python 3.12 nflverse load-samples
uv run --python 3.12 nflverse test-reimport
```

By default, the loader reads and parses the full original Parquet files but only
loads the first 10,000 rows from high-volume fact/event assets into PostgreSQL.
Reference assets for schedules, teams, players and weekly rosters are loaded
uncapped. Use `--sample-row-limit 0` to load the full selected files.

The report is written to `data/reports/nflverse_sample_report.json`.

## Relationship checks

The validation command checks:

- 2024 schedule home and away teams join to `teams`.
- Weekly roster, player stats and team stats team abbreviations join to `teams`.
- PBP and snap-count game IDs join to `games`.
- Weekly roster and player-stat player IDs join to `players`.
- Snap-count PFR IDs join to `player_id_mappings`.

`test-reimport` loads the same sample twice and compares row counts before and
after the second import.

## Verification run

Verified on 2026-09-30 using the commands in this document against a temporary
local PostgreSQL database.

Downloaded and parsed one Parquet release asset from each selected release.
GitHub SHA-256 digests were verified when available. `weekly_rosters` did not
publish a digest for `roster_weekly_2024.parquet`, so the local SHA-256 was
computed and stored in `data/raw/nflverse/manifest.json`.

`nflverse load-samples` passed all relationship checks:

| Table | Rows |
| --- | ---: |
| `nflverse.asset_imports` | 8 |
| `nflverse.games` | 7,548 |
| `nflverse.teams` | 36 |
| `nflverse.players` | 25,036 |
| `nflverse.player_id_mappings` | 70,307 |
| `nflverse.weekly_rosters` | 46,572 |
| `nflverse.player_stats_weekly` | 9,991 |
| `nflverse.team_stats_weekly` | 570 |
| `nflverse.pbp` | 10,000 |
| `nflverse.snap_counts` | 10,000 |
| `football.dim_teams` | 36 |
| `football.dim_players` | 25,036 |
| `football.xref_player_ids` | 70,307 |
| `football.fact_games` | 7,548 |
| `football.fact_events` | 10,000 |
| `football.fact_player_team_weeks` | 46,572 |
| `football.fact_player_week_stats` | 9,991 |
| `football.fact_team_week_stats` | 570 |
| `football.fact_snap_counts` | 10,000 |

Relationship failure counts were zero for game, team and player checks.
`test-reimport` returned identical before/after row counts and
`reimport_idempotent: true`.

## Refresh cadence

Use the nflreadr schedule documentation as the operating source:
[nflverse Data Update and Availability Schedule](https://nflreadr.nflverse.com/articles/nflverse_data_schedule.html).

First-build cadence:

- Check changed PBP, player stats, team stats, schedules and snap-count assets
  after game days, but do not assume files are ready immediately after the final
  whistle.
- Recheck Thursday morning for stat corrections. The nflreadr schedule notes
  that Thursday data is the cleanest after NFL corrections from Monday through
  Wednesday.
- Refresh player and weekly roster reference data daily.
- Refresh team reference data when release asset metadata changes.

## Attribution

Data comes from nflverse/nflverse-data and the upstream sources documented by
nflverse. Keep source URLs and release asset metadata with imported data. Any
published analysis, app screen, export, or model output using this data should
attribute nflverse and link to the nflverse data repository.

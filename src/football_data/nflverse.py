from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.request import Request, urlopen

import pandas as pd
import psycopg


GITHUB_API = "https://api.github.com/repos/nflverse/nflverse-data/releases/tags/{tag}"
DEFAULT_DATABASE_URL = "postgresql://football:football@localhost:5432/football_analytics"
DEFAULT_RAW_DIR = Path("data/raw/nflverse")
DEFAULT_REPORT = Path("data/reports/nflverse_sample_report.json")
DEFAULT_SAMPLE_ROW_LIMIT = 10_000
SAMPLE_ROW_LIMIT = DEFAULT_SAMPLE_ROW_LIMIT


SAMPLE_ASSETS = {
    "schedules": "games.parquet",
    "teams": "teams_colors_logos.parquet",
    "players": "players.parquet",
    "weekly_rosters": "roster_weekly_2024.parquet",
    "pbp": "play_by_play_2024.parquet",
    "stats_player": "stats_player_week_2024.parquet",
    "stats_team": "stats_team_week_2024.parquet",
    "snap_counts": "snap_counts_2024.parquet",
}

HIGH_VOLUME_SAMPLE_ASSETS = {
    "play_by_play_2024.parquet",
    "stats_player_week_2024.parquet",
    "stats_team_week_2024.parquet",
    "snap_counts_2024.parquet",
}


@dataclass(frozen=True)
class Asset:
    tag: str
    asset_id: int
    name: str
    digest: str | None
    updated_at: str
    size: int
    download_url: str
    release_url: str

    @property
    def local_path(self) -> Path:
        return DEFAULT_RAW_DIR / self.tag / self.name


def fetch_release(tag: str) -> dict[str, Any]:
    request = Request(GITHUB_API.format(tag=tag), headers={"Accept": "application/vnd.github+json"})
    with urlopen(request, timeout=60) as response:
        return json.load(response)


def selected_assets() -> list[Asset]:
    assets: list[Asset] = []
    for tag, name in SAMPLE_ASSETS.items():
        release = fetch_release(tag)
        matches = [asset for asset in release["assets"] if asset["name"] == name]
        if not matches:
            raise SystemExit(f"Could not find asset {name!r} on release tag {tag!r}")
        asset = matches[0]
        assets.append(
            Asset(
                tag=tag,
                asset_id=asset["id"],
                name=asset["name"],
                digest=asset.get("digest"),
                updated_at=asset["updated_at"],
                size=asset["size"],
                download_url=asset["browser_download_url"],
                release_url=release["html_url"],
            )
        )
    return assets


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_sha(asset: Asset) -> str | None:
    if asset.digest and asset.digest.startswith("sha256:"):
        return asset.digest.split(":", 1)[1]
    return None


def download_file(asset: Asset) -> dict[str, Any]:
    path = asset.local_path
    path.parent.mkdir(parents=True, exist_ok=True)
    expected = expected_sha(asset)

    if path.exists() and path.stat().st_size == asset.size:
        local_sha = sha256_file(path)
        if expected is None or local_sha == expected:
            return manifest_row(asset, path, local_sha, skipped=True)

    tmp_path = path.with_suffix(path.suffix + ".tmp")
    request = Request(asset.download_url, headers={"Accept": "application/octet-stream"})
    with urlopen(request, timeout=300) as response, tmp_path.open("wb") as handle:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
    tmp_path.replace(path)

    local_sha = sha256_file(path)
    if expected and local_sha != expected:
        raise SystemExit(f"Checksum mismatch for {asset.name}: expected {expected}, got {local_sha}")
    return manifest_row(asset, path, local_sha, skipped=False)


def manifest_row(asset: Asset, path: Path, local_sha: str, skipped: bool) -> dict[str, Any]:
    return {
        "tag": asset.tag,
        "asset_name": asset.name,
        "asset_id": asset.asset_id,
        "source_updated_at": asset.updated_at,
        "source_size": asset.size,
        "source_digest": asset.digest,
        "local_path": str(path),
        "local_sha256": local_sha,
        "browser_download_url": asset.download_url,
        "release_url": asset.release_url,
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "skipped_existing_file": skipped,
    }


def write_manifest(rows: list[dict[str, Any]]) -> None:
    DEFAULT_RAW_DIR.mkdir(parents=True, exist_ok=True)
    (DEFAULT_RAW_DIR / "manifest.json").write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n")


def read_manifest() -> list[dict[str, Any]]:
    path = DEFAULT_RAW_DIR / "manifest.json"
    if not path.exists():
        raise SystemExit("No manifest found. Run `nflverse download-samples` first.")
    return json.loads(path.read_text())


def connect(database_url: str) -> psycopg.Connection:
    return psycopg.connect(database_url, autocommit=False)


def create_schema(conn: psycopg.Connection) -> None:
    statements = [
        "CREATE SCHEMA IF NOT EXISTS nflverse",
        "CREATE SCHEMA IF NOT EXISTS football",
        """
        CREATE TABLE IF NOT EXISTS nflverse.asset_imports (
            tag text NOT NULL,
            asset_name text NOT NULL,
            asset_id bigint NOT NULL,
            source_updated_at timestamptz NOT NULL,
            source_size bigint NOT NULL,
            source_digest text,
            browser_download_url text NOT NULL,
            release_url text NOT NULL,
            local_sha256 text NOT NULL,
            row_count integer NOT NULL,
            imported_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tag, asset_name)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS nflverse.teams (
            team_abbr text PRIMARY KEY,
            team_name text,
            team_id text,
            team_color text,
            team_color2 text,
            team_logo_espn text,
            source_asset text NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS nflverse.games (
            game_id text PRIMARY KEY,
            season integer,
            week integer,
            game_type text,
            gameday date,
            home_team text,
            away_team text,
            home_score integer,
            away_score integer,
            source_asset text NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS nflverse.players (
            gsis_id text PRIMARY KEY,
            display_name text,
            first_name text,
            last_name text,
            position text,
            pfr_id text,
            espn_id text,
            sportradar_id text,
            source_asset text NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS nflverse.player_id_mappings (
            provider text NOT NULL,
            provider_player_id text NOT NULL,
            gsis_id text NOT NULL,
            source_asset text NOT NULL,
            PRIMARY KEY (provider, provider_player_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS nflverse.weekly_rosters (
            season integer NOT NULL,
            week integer NOT NULL,
            player_id text NOT NULL,
            gsis_id text,
            team text NOT NULL,
            player_name text,
            position text,
            status text,
            source_asset text NOT NULL,
            PRIMARY KEY (season, week, player_id, team)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS nflverse.player_stats_weekly (
            season integer NOT NULL,
            week integer NOT NULL,
            player_id text NOT NULL,
            team text NOT NULL,
            player_name text,
            position text,
            source_asset text NOT NULL,
            PRIMARY KEY (season, week, player_id, team)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS nflverse.team_stats_weekly (
            season integer NOT NULL,
            week integer NOT NULL,
            team text NOT NULL,
            source_asset text NOT NULL,
            PRIMARY KEY (season, week, team)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS nflverse.pbp (
            game_id text NOT NULL,
            play_id integer NOT NULL,
            season integer,
            week integer,
            posteam text,
            defteam text,
            desc_text text,
            source_asset text NOT NULL,
            PRIMARY KEY (game_id, play_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS nflverse.snap_counts (
            game_id text NOT NULL,
            player_id text NOT NULL,
            team text NOT NULL,
            season integer,
            week integer,
            player_name text,
            position text,
            offense_snaps integer,
            defense_snaps integer,
            st_snaps integer,
            source_asset text NOT NULL,
            PRIMARY KEY (game_id, player_id, team)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS football.dim_teams (
            team_abbr text PRIMARY KEY,
            team_name text,
            nflverse_team_id text,
            primary_color text,
            secondary_color text,
            logo_url text,
            source_asset text NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS football.dim_players (
            gsis_id text PRIMARY KEY,
            display_name text,
            first_name text,
            last_name text,
            position text,
            source_asset text NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS football.xref_player_ids (
            provider text NOT NULL,
            provider_player_id text NOT NULL,
            gsis_id text NOT NULL REFERENCES football.dim_players(gsis_id),
            source_asset text NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (provider, provider_player_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS football.fact_games (
            game_id text PRIMARY KEY,
            season integer NOT NULL,
            week integer NOT NULL,
            season_type text,
            game_date date,
            home_team text REFERENCES football.dim_teams(team_abbr),
            away_team text REFERENCES football.dim_teams(team_abbr),
            home_score integer,
            away_score integer,
            source_asset text NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS football.fact_events (
            game_id text NOT NULL REFERENCES football.fact_games(game_id),
            play_id integer NOT NULL,
            season integer,
            week integer,
            possession_team text REFERENCES football.dim_teams(team_abbr),
            defense_team text REFERENCES football.dim_teams(team_abbr),
            description text,
            source_asset text NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (game_id, play_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS football.fact_player_team_weeks (
            season integer NOT NULL,
            week integer NOT NULL,
            player_id text NOT NULL REFERENCES football.dim_players(gsis_id),
            team text NOT NULL REFERENCES football.dim_teams(team_abbr),
            player_name text,
            position text,
            status text,
            source_asset text NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (season, week, player_id, team)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS football.fact_player_week_stats (
            season integer NOT NULL,
            week integer NOT NULL,
            player_id text NOT NULL REFERENCES football.dim_players(gsis_id),
            team text NOT NULL REFERENCES football.dim_teams(team_abbr),
            player_name text,
            position text,
            source_asset text NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (season, week, player_id, team)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS football.fact_team_week_stats (
            season integer NOT NULL,
            week integer NOT NULL,
            team text NOT NULL REFERENCES football.dim_teams(team_abbr),
            source_asset text NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (season, week, team)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS football.fact_snap_counts (
            game_id text NOT NULL REFERENCES football.fact_games(game_id),
            player_id text NOT NULL REFERENCES football.dim_players(gsis_id),
            team text NOT NULL REFERENCES football.dim_teams(team_abbr),
            season integer,
            week integer,
            player_name text,
            position text,
            offense_snaps integer,
            defense_snaps integer,
            special_teams_snaps integer,
            source_asset text NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (game_id, player_id, team)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_fact_games_season_week ON football.fact_games(season, week)",
        "CREATE INDEX IF NOT EXISTS idx_fact_events_game ON football.fact_events(game_id)",
        "CREATE INDEX IF NOT EXISTS idx_fact_player_week_stats_player ON football.fact_player_week_stats(player_id)",
        "CREATE INDEX IF NOT EXISTS idx_fact_snap_counts_player ON football.fact_snap_counts(player_id)",
    ]
    with conn.cursor() as cur:
        for statement in statements:
            cur.execute(statement)
    conn.commit()


def read_asset_frame(manifest: list[dict[str, Any]], asset_name: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    row = next((item for item in manifest if item["asset_name"] == asset_name), None)
    if row is None:
        raise SystemExit(f"Manifest is missing {asset_name}. Run `nflverse download-samples` again.")
    path = Path(row["local_path"])
    if not path.exists():
        raise SystemExit(f"Downloaded asset is missing: {path}")
    df = pd.read_parquet(path)
    if asset_name in HIGH_VOLUME_SAMPLE_ASSETS and SAMPLE_ROW_LIMIT > 0:
        df = df.head(SAMPLE_ROW_LIMIT)
    return df, row


def clean(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, pd.Timestamp):
        return value.date()
    return value


def text(value: Any) -> str | None:
    value = clean(value)
    if value is None:
        return None
    return str(value)


def integer(value: Any) -> int | None:
    value = clean(value)
    if value is None or value == "":
        return None
    return int(float(value))


def row_get(row: pd.Series, *names: str) -> Any:
    for name in names:
        if name in row:
            value = clean(row[name])
            if value is not None:
                return value
    return None


def upsert_many(conn: psycopg.Connection, sql: str, rows: Iterable[tuple[Any, ...]]) -> int:
    prepared = list(rows)
    if not prepared:
        return 0
    with conn.cursor() as cur:
        cur.executemany(sql, prepared)
    return len(prepared)


def load_asset_import(conn: psycopg.Connection, manifest_row_data: dict[str, Any], row_count: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO nflverse.asset_imports (
                tag, asset_name, asset_id, source_updated_at, source_size, source_digest,
                browser_download_url, release_url, local_sha256, row_count, imported_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (tag, asset_name) DO UPDATE SET
                asset_id = EXCLUDED.asset_id,
                source_updated_at = EXCLUDED.source_updated_at,
                source_size = EXCLUDED.source_size,
                source_digest = EXCLUDED.source_digest,
                browser_download_url = EXCLUDED.browser_download_url,
                release_url = EXCLUDED.release_url,
                local_sha256 = EXCLUDED.local_sha256,
                row_count = EXCLUDED.row_count,
                imported_at = now()
            """,
            (
                manifest_row_data["tag"],
                manifest_row_data["asset_name"],
                manifest_row_data["asset_id"],
                manifest_row_data["source_updated_at"],
                manifest_row_data["source_size"],
                manifest_row_data["source_digest"],
                manifest_row_data["browser_download_url"],
                manifest_row_data["release_url"],
                manifest_row_data["local_sha256"],
                row_count,
            ),
        )


def load_teams(conn: psycopg.Connection, manifest: list[dict[str, Any]]) -> int:
    df, asset = read_asset_frame(manifest, SAMPLE_ASSETS["teams"])
    count = upsert_many(
        conn,
        """
        INSERT INTO nflverse.teams (team_abbr, team_name, team_id, team_color, team_color2, team_logo_espn, source_asset)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (team_abbr) DO UPDATE SET
            team_name = EXCLUDED.team_name,
            team_id = EXCLUDED.team_id,
            team_color = EXCLUDED.team_color,
            team_color2 = EXCLUDED.team_color2,
            team_logo_espn = EXCLUDED.team_logo_espn,
            source_asset = EXCLUDED.source_asset
        """,
        (
            (
                text(row_get(row, "team_abbr")),
                text(row_get(row, "team_name", "team_nick")),
                text(row_get(row, "team_id")),
                text(row_get(row, "team_color")),
                text(row_get(row, "team_color2")),
                text(row_get(row, "team_logo_espn", "team_logo_wikipedia")),
                asset["asset_name"],
            )
            for _, row in df.iterrows()
            if text(row_get(row, "team_abbr"))
        ),
    )
    load_asset_import(conn, asset, len(df))
    return count


def load_games(conn: psycopg.Connection, manifest: list[dict[str, Any]]) -> int:
    df, asset = read_asset_frame(manifest, SAMPLE_ASSETS["schedules"])
    count = upsert_many(
        conn,
        """
        INSERT INTO nflverse.games (
            game_id, season, week, game_type, gameday, home_team, away_team, home_score, away_score, source_asset
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (game_id) DO UPDATE SET
            season = EXCLUDED.season,
            week = EXCLUDED.week,
            game_type = EXCLUDED.game_type,
            gameday = EXCLUDED.gameday,
            home_team = EXCLUDED.home_team,
            away_team = EXCLUDED.away_team,
            home_score = EXCLUDED.home_score,
            away_score = EXCLUDED.away_score,
            source_asset = EXCLUDED.source_asset
        """,
        (
            (
                text(row_get(row, "game_id")),
                integer(row_get(row, "season")),
                integer(row_get(row, "week")),
                text(row_get(row, "game_type")),
                clean(row_get(row, "gameday", "game_date")),
                text(row_get(row, "home_team")),
                text(row_get(row, "away_team")),
                integer(row_get(row, "home_score")),
                integer(row_get(row, "away_score")),
                asset["asset_name"],
            )
            for _, row in df.iterrows()
            if text(row_get(row, "game_id"))
        ),
    )
    load_asset_import(conn, asset, len(df))
    return count


def load_players(conn: psycopg.Connection, manifest: list[dict[str, Any]]) -> int:
    df, asset = read_asset_frame(manifest, SAMPLE_ASSETS["players"])
    rows = []
    mapping_rows = []
    provider_columns = {
        "gsis": ["gsis_id", "gsis_it_id", "old_gsis_id"],
        "pfr": ["pfr_id"],
        "espn": ["espn_id"],
        "sportradar": ["sportradar_id"],
        "yahoo": ["yahoo_id"],
        "sleeper": ["sleeper_id"],
    }
    for _, row in df.iterrows():
        gsis_id = text(row_get(row, "gsis_id"))
        if not gsis_id:
            continue
        rows.append(
            (
                gsis_id,
                text(row_get(row, "display_name", "full_name", "football_name")),
                text(row_get(row, "first_name")),
                text(row_get(row, "last_name")),
                text(row_get(row, "position")),
                text(row_get(row, "pfr_id")),
                text(row_get(row, "espn_id")),
                text(row_get(row, "sportradar_id")),
                asset["asset_name"],
            )
        )
        for provider, columns in provider_columns.items():
            for column in columns:
                value = text(row_get(row, column))
                if value:
                    mapping_rows.append((provider, value, gsis_id, asset["asset_name"]))
    count = upsert_many(
        conn,
        """
        INSERT INTO nflverse.players (
            gsis_id, display_name, first_name, last_name, position, pfr_id, espn_id, sportradar_id, source_asset
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (gsis_id) DO UPDATE SET
            display_name = EXCLUDED.display_name,
            first_name = EXCLUDED.first_name,
            last_name = EXCLUDED.last_name,
            position = EXCLUDED.position,
            pfr_id = EXCLUDED.pfr_id,
            espn_id = EXCLUDED.espn_id,
            sportradar_id = EXCLUDED.sportradar_id,
            source_asset = EXCLUDED.source_asset
        """,
        rows,
    )
    upsert_many(
        conn,
        """
        INSERT INTO nflverse.player_id_mappings (provider, provider_player_id, gsis_id, source_asset)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (provider, provider_player_id) DO UPDATE SET
            gsis_id = EXCLUDED.gsis_id,
            source_asset = EXCLUDED.source_asset
        """,
        mapping_rows,
    )
    load_asset_import(conn, asset, len(df))
    return count


def load_weekly_rosters(conn: psycopg.Connection, manifest: list[dict[str, Any]]) -> int:
    df, asset = read_asset_frame(manifest, SAMPLE_ASSETS["weekly_rosters"])
    roster_rows = []
    supplemental_players = []
    mapping_rows = []
    provider_columns = {
        "pfr": ["pfr_id"],
        "espn": ["espn_id"],
        "sportradar": ["sportradar_id"],
        "yahoo": ["yahoo_id"],
        "sleeper": ["sleeper_id"],
    }
    for _, row in df.iterrows():
        season = integer(row_get(row, "season"))
        week = integer(row_get(row, "week"))
        player_id = text(row_get(row, "player_id", "gsis_id"))
        gsis_id = text(row_get(row, "gsis_id", "player_id"))
        team = text(row_get(row, "team", "recent_team"))
        player_name = text(row_get(row, "full_name", "player_name", "display_name"))
        position = text(row_get(row, "position"))
        status = text(row_get(row, "status"))
        if season is None or week is None or not player_id or not team:
            continue
        roster_rows.append((season, week, player_id, gsis_id, team, player_name, position, status, asset["asset_name"]))
        if gsis_id:
            supplemental_players.append(
                (
                    gsis_id,
                    player_name,
                    text(row_get(row, "first_name")),
                    text(row_get(row, "last_name")),
                    position,
                    text(row_get(row, "pfr_id")),
                    text(row_get(row, "espn_id")),
                    text(row_get(row, "sportradar_id")),
                    asset["asset_name"],
                )
            )
            mapping_rows.append(("gsis", gsis_id, gsis_id, asset["asset_name"]))
            for provider, columns in provider_columns.items():
                for column in columns:
                    value = text(row_get(row, column))
                    if value:
                        mapping_rows.append((provider, value, gsis_id, asset["asset_name"]))

    upsert_many(
        conn,
        """
        INSERT INTO nflverse.players (
            gsis_id, display_name, first_name, last_name, position, pfr_id, espn_id, sportradar_id, source_asset
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (gsis_id) DO UPDATE SET
            display_name = coalesce(nflverse.players.display_name, EXCLUDED.display_name),
            first_name = coalesce(nflverse.players.first_name, EXCLUDED.first_name),
            last_name = coalesce(nflverse.players.last_name, EXCLUDED.last_name),
            position = coalesce(nflverse.players.position, EXCLUDED.position),
            pfr_id = coalesce(nflverse.players.pfr_id, EXCLUDED.pfr_id),
            espn_id = coalesce(nflverse.players.espn_id, EXCLUDED.espn_id),
            sportradar_id = coalesce(nflverse.players.sportradar_id, EXCLUDED.sportradar_id),
            source_asset = nflverse.players.source_asset
        """,
        supplemental_players,
    )
    upsert_many(
        conn,
        """
        INSERT INTO nflverse.player_id_mappings (provider, provider_player_id, gsis_id, source_asset)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (provider, provider_player_id) DO UPDATE SET
            gsis_id = EXCLUDED.gsis_id,
            source_asset = EXCLUDED.source_asset
        """,
        mapping_rows,
    )
    count = upsert_many(
        conn,
        """
        INSERT INTO nflverse.weekly_rosters (
            season, week, player_id, gsis_id, team, player_name, position, status, source_asset
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (season, week, player_id, team) DO UPDATE SET
            gsis_id = EXCLUDED.gsis_id,
            player_name = EXCLUDED.player_name,
            position = EXCLUDED.position,
            status = EXCLUDED.status,
            source_asset = EXCLUDED.source_asset
        """,
        roster_rows,
    )
    load_asset_import(conn, asset, len(df))
    return count


def load_player_stats(conn: psycopg.Connection, manifest: list[dict[str, Any]]) -> int:
    df, asset = read_asset_frame(manifest, SAMPLE_ASSETS["stats_player"])
    count = upsert_many(
        conn,
        """
        INSERT INTO nflverse.player_stats_weekly (season, week, player_id, team, player_name, position, source_asset)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (season, week, player_id, team) DO UPDATE SET
            player_name = EXCLUDED.player_name,
            position = EXCLUDED.position,
            source_asset = EXCLUDED.source_asset
        """,
        (
            (
                integer(row_get(row, "season")),
                integer(row_get(row, "week")),
                text(row_get(row, "player_id", "gsis_id")),
                text(row_get(row, "recent_team", "team")),
                text(row_get(row, "player_display_name", "player_name", "display_name")),
                text(row_get(row, "position", "position_group")),
                asset["asset_name"],
            )
            for _, row in df.iterrows()
            if row_get(row, "season") is not None and row_get(row, "week") is not None and text(row_get(row, "player_id", "gsis_id")) and text(row_get(row, "recent_team", "team"))
        ),
    )
    load_asset_import(conn, asset, len(df))
    return count


def load_team_stats(conn: psycopg.Connection, manifest: list[dict[str, Any]]) -> int:
    df, asset = read_asset_frame(manifest, SAMPLE_ASSETS["stats_team"])
    count = upsert_many(
        conn,
        """
        INSERT INTO nflverse.team_stats_weekly (season, week, team, source_asset)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (season, week, team) DO UPDATE SET
            source_asset = EXCLUDED.source_asset
        """,
        (
            (
                integer(row_get(row, "season")),
                integer(row_get(row, "week")),
                text(row_get(row, "team", "recent_team")),
                asset["asset_name"],
            )
            for _, row in df.iterrows()
            if row_get(row, "season") is not None and row_get(row, "week") is not None and text(row_get(row, "team", "recent_team"))
        ),
    )
    load_asset_import(conn, asset, len(df))
    return count


def load_pbp(conn: psycopg.Connection, manifest: list[dict[str, Any]]) -> int:
    df, asset = read_asset_frame(manifest, SAMPLE_ASSETS["pbp"])
    count = upsert_many(
        conn,
        """
        INSERT INTO nflverse.pbp (game_id, play_id, season, week, posteam, defteam, desc_text, source_asset)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (game_id, play_id) DO UPDATE SET
            season = EXCLUDED.season,
            week = EXCLUDED.week,
            posteam = EXCLUDED.posteam,
            defteam = EXCLUDED.defteam,
            desc_text = EXCLUDED.desc_text,
            source_asset = EXCLUDED.source_asset
        """,
        (
            (
                text(row_get(row, "game_id")),
                integer(row_get(row, "play_id")),
                integer(row_get(row, "season")),
                integer(row_get(row, "week")),
                text(row_get(row, "posteam")),
                text(row_get(row, "defteam")),
                text(row_get(row, "desc")),
                asset["asset_name"],
            )
            for _, row in df.iterrows()
            if text(row_get(row, "game_id")) and row_get(row, "play_id") is not None
        ),
    )
    load_asset_import(conn, asset, len(df))
    return count


def load_snap_counts(conn: psycopg.Connection, manifest: list[dict[str, Any]]) -> int:
    df, asset = read_asset_frame(manifest, SAMPLE_ASSETS["snap_counts"])
    count = upsert_many(
        conn,
        """
        INSERT INTO nflverse.snap_counts (
            game_id, player_id, team, season, week, player_name, position,
            offense_snaps, defense_snaps, st_snaps, source_asset
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (game_id, player_id, team) DO UPDATE SET
            season = EXCLUDED.season,
            week = EXCLUDED.week,
            player_name = EXCLUDED.player_name,
            position = EXCLUDED.position,
            offense_snaps = EXCLUDED.offense_snaps,
            defense_snaps = EXCLUDED.defense_snaps,
            st_snaps = EXCLUDED.st_snaps,
            source_asset = EXCLUDED.source_asset
        """,
        (
            (
                text(row_get(row, "game_id")),
                text(row_get(row, "pfr_player_id", "player_id", "gsis_id")),
                text(row_get(row, "team", "recent_team")),
                integer(row_get(row, "season")),
                integer(row_get(row, "week")),
                text(row_get(row, "player", "player_name")),
                text(row_get(row, "position")),
                integer(row_get(row, "offense_snaps")),
                integer(row_get(row, "defense_snaps")),
                integer(row_get(row, "st_snaps")),
                asset["asset_name"],
            )
            for _, row in df.iterrows()
            if text(row_get(row, "game_id")) and text(row_get(row, "pfr_player_id", "player_id", "gsis_id")) and text(row_get(row, "team", "recent_team"))
        ),
    )
    load_asset_import(conn, asset, len(df))
    return count


LOADERS = [
    load_teams,
    load_games,
    load_players,
    load_weekly_rosters,
    load_player_stats,
    load_team_stats,
    load_pbp,
    load_snap_counts,
]


def normalized_name(value: str | bytes | None) -> str:
    if not value:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="ignore")
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", value.lower())
    tokens = [token for token in cleaned.split() if token not in {"jr", "sr", "ii", "iii", "iv", "v"}]
    return " ".join(tokens)


def last_name_token(value: str | bytes | None) -> str:
    normalized = normalized_name(value)
    if not normalized:
        return ""
    return normalized.split()[-1]


def derive_snap_player_mappings(conn: psycopg.Connection) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT s.player_id, s.player_name, s.team, s.season, s.week, s.position, s.source_asset
            FROM nflverse.snap_counts s
            LEFT JOIN nflverse.player_id_mappings m
              ON m.provider = 'pfr' AND m.provider_player_id = s.player_id
            WHERE m.provider_player_id IS NULL
            """
        )
        snaps = cur.fetchall()
        cur.execute(
            """
            SELECT season, week, team, player_name, gsis_id, position
            FROM nflverse.weekly_rosters
            WHERE gsis_id IS NOT NULL
            """
        )
        rosters = cur.fetchall()

    roster_index: dict[tuple[int, int, str], list[tuple[str, str, str, str]]] = {}
    for season, week, team, player_name, gsis_id, position in rosters:
        roster_index.setdefault((season, week, team), []).append(
            (normalized_name(player_name), last_name_token(player_name), gsis_id, position or "")
        )

    by_pfr: dict[str, dict[str, Any]] = {}
    for player_id, player_name, team, season, week, position, source_asset in snaps:
        by_pfr.setdefault(player_id, {"rows": [], "source_asset": source_asset})["rows"].append(
            {
                "name": player_name,
                "team": team,
                "season": season,
                "week": week,
                "position": position or "",
            }
        )

    derived_rows = []
    for pfr_id, payload in by_pfr.items():
        candidate_gsis: set[str] = set()
        for snap in payload["rows"]:
            roster_rows = roster_index.get((snap["season"], snap["week"], snap["team"]), [])
            snap_name = normalized_name(snap["name"])
            snap_last_name = last_name_token(snap["name"])
            exact = {gsis_id for name, _, gsis_id, _ in roster_rows if name == snap_name}
            if exact:
                candidate_gsis.update(exact)
                continue
            loose = {
                gsis_id
                for _, last_name, gsis_id, roster_position in roster_rows
                if snap_last_name and last_name == snap_last_name and roster_position == snap["position"]
            }
            candidate_gsis.update(loose)
        if len(candidate_gsis) == 1:
            derived_rows.append(("pfr", pfr_id, next(iter(candidate_gsis)), payload["source_asset"]))

    return upsert_many(
        conn,
        """
        INSERT INTO nflverse.player_id_mappings (provider, provider_player_id, gsis_id, source_asset)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (provider, provider_player_id) DO UPDATE SET
            gsis_id = EXCLUDED.gsis_id,
            source_asset = EXCLUDED.source_asset
        """,
        derived_rows,
    )


def sync_model_tables(conn: psycopg.Connection) -> dict[str, int]:
    statements = {
        "dim_teams": """
            INSERT INTO football.dim_teams (
                team_abbr, team_name, nflverse_team_id, primary_color, secondary_color, logo_url, source_asset, updated_at
            )
            SELECT team_abbr, team_name, team_id, team_color, team_color2, team_logo_espn, source_asset, now()
            FROM nflverse.teams
            ON CONFLICT (team_abbr) DO UPDATE SET
                team_name = EXCLUDED.team_name,
                nflverse_team_id = EXCLUDED.nflverse_team_id,
                primary_color = EXCLUDED.primary_color,
                secondary_color = EXCLUDED.secondary_color,
                logo_url = EXCLUDED.logo_url,
                source_asset = EXCLUDED.source_asset,
                updated_at = now()
        """,
        "dim_players": """
            INSERT INTO football.dim_players (
                gsis_id, display_name, first_name, last_name, position, source_asset, updated_at
            )
            SELECT gsis_id, display_name, first_name, last_name, position, source_asset, now()
            FROM nflverse.players
            ON CONFLICT (gsis_id) DO UPDATE SET
                display_name = EXCLUDED.display_name,
                first_name = EXCLUDED.first_name,
                last_name = EXCLUDED.last_name,
                position = EXCLUDED.position,
                source_asset = EXCLUDED.source_asset,
                updated_at = now()
        """,
        "xref_player_ids": """
            INSERT INTO football.xref_player_ids (
                provider, provider_player_id, gsis_id, source_asset, updated_at
            )
            SELECT provider, provider_player_id, gsis_id, source_asset, now()
            FROM nflverse.player_id_mappings
            WHERE gsis_id IN (SELECT gsis_id FROM football.dim_players)
            ON CONFLICT (provider, provider_player_id) DO UPDATE SET
                gsis_id = EXCLUDED.gsis_id,
                source_asset = EXCLUDED.source_asset,
                updated_at = now()
        """,
        "fact_games": """
            INSERT INTO football.fact_games (
                game_id, season, week, season_type, game_date, home_team, away_team,
                home_score, away_score, source_asset, updated_at
            )
            SELECT game_id, season, week, game_type, gameday, home_team, away_team,
                   home_score, away_score, source_asset, now()
            FROM nflverse.games
            WHERE game_id IS NOT NULL
              AND season IS NOT NULL
              AND week IS NOT NULL
              AND (home_team IS NULL OR home_team IN (SELECT team_abbr FROM football.dim_teams))
              AND (away_team IS NULL OR away_team IN (SELECT team_abbr FROM football.dim_teams))
            ON CONFLICT (game_id) DO UPDATE SET
                season = EXCLUDED.season,
                week = EXCLUDED.week,
                season_type = EXCLUDED.season_type,
                game_date = EXCLUDED.game_date,
                home_team = EXCLUDED.home_team,
                away_team = EXCLUDED.away_team,
                home_score = EXCLUDED.home_score,
                away_score = EXCLUDED.away_score,
                source_asset = EXCLUDED.source_asset,
                updated_at = now()
        """,
        "fact_events": """
            INSERT INTO football.fact_events (
                game_id, play_id, season, week, possession_team, defense_team,
                description, source_asset, updated_at
            )
            SELECT p.game_id, p.play_id, p.season, p.week, p.posteam, p.defteam,
                   p.desc_text, p.source_asset, now()
            FROM nflverse.pbp p
            WHERE p.game_id IN (SELECT game_id FROM football.fact_games)
              AND p.play_id IS NOT NULL
              AND (p.posteam IS NULL OR p.posteam IN (SELECT team_abbr FROM football.dim_teams))
              AND (p.defteam IS NULL OR p.defteam IN (SELECT team_abbr FROM football.dim_teams))
            ON CONFLICT (game_id, play_id) DO UPDATE SET
                season = EXCLUDED.season,
                week = EXCLUDED.week,
                possession_team = EXCLUDED.possession_team,
                defense_team = EXCLUDED.defense_team,
                description = EXCLUDED.description,
                source_asset = EXCLUDED.source_asset,
                updated_at = now()
        """,
        "fact_player_team_weeks": """
            INSERT INTO football.fact_player_team_weeks (
                season, week, player_id, team, player_name, position, status, source_asset, updated_at
            )
            SELECT season, week, coalesce(gsis_id, player_id), team, player_name,
                   position, status, source_asset, now()
            FROM nflverse.weekly_rosters
            WHERE coalesce(gsis_id, player_id) IN (SELECT gsis_id FROM football.dim_players)
              AND team IN (SELECT team_abbr FROM football.dim_teams)
            ON CONFLICT (season, week, player_id, team) DO UPDATE SET
                player_name = EXCLUDED.player_name,
                position = EXCLUDED.position,
                status = EXCLUDED.status,
                source_asset = EXCLUDED.source_asset,
                updated_at = now()
        """,
        "fact_player_week_stats": """
            INSERT INTO football.fact_player_week_stats (
                season, week, player_id, team, player_name, position, source_asset, updated_at
            )
            SELECT season, week, player_id, team, player_name, position, source_asset, now()
            FROM nflverse.player_stats_weekly
            WHERE player_id IN (SELECT gsis_id FROM football.dim_players)
              AND team IN (SELECT team_abbr FROM football.dim_teams)
            ON CONFLICT (season, week, player_id, team) DO UPDATE SET
                player_name = EXCLUDED.player_name,
                position = EXCLUDED.position,
                source_asset = EXCLUDED.source_asset,
                updated_at = now()
        """,
        "fact_team_week_stats": """
            INSERT INTO football.fact_team_week_stats (season, week, team, source_asset, updated_at)
            SELECT season, week, team, source_asset, now()
            FROM nflverse.team_stats_weekly
            WHERE team IN (SELECT team_abbr FROM football.dim_teams)
            ON CONFLICT (season, week, team) DO UPDATE SET
                source_asset = EXCLUDED.source_asset,
                updated_at = now()
        """,
        "fact_snap_counts": """
            INSERT INTO football.fact_snap_counts (
                game_id, player_id, team, season, week, player_name, position,
                offense_snaps, defense_snaps, special_teams_snaps, source_asset, updated_at
            )
            SELECT s.game_id, coalesce(m.gsis_id, s.player_id), s.team, s.season, s.week,
                   s.player_name, s.position, s.offense_snaps, s.defense_snaps, s.st_snaps,
                   s.source_asset, now()
            FROM nflverse.snap_counts s
            LEFT JOIN nflverse.player_id_mappings m
              ON m.provider = 'pfr' AND m.provider_player_id = s.player_id
            WHERE s.game_id IN (SELECT game_id FROM football.fact_games)
              AND coalesce(m.gsis_id, s.player_id) IN (SELECT gsis_id FROM football.dim_players)
              AND s.team IN (SELECT team_abbr FROM football.dim_teams)
            ON CONFLICT (game_id, player_id, team) DO UPDATE SET
                season = EXCLUDED.season,
                week = EXCLUDED.week,
                player_name = EXCLUDED.player_name,
                position = EXCLUDED.position,
                offense_snaps = EXCLUDED.offense_snaps,
                defense_snaps = EXCLUDED.defense_snaps,
                special_teams_snaps = EXCLUDED.special_teams_snaps,
                source_asset = EXCLUDED.source_asset,
                updated_at = now()
        """,
    }
    counts: dict[str, int] = {}
    with conn.cursor() as cur:
        for table, sql in statements.items():
            cur.execute(sql)
            counts[table] = cur.rowcount
    return counts


def table_counts(conn: psycopg.Connection) -> dict[str, int]:
    tables = [
        ("nflverse", "asset_imports"),
        ("nflverse", "teams"),
        ("nflverse", "games"),
        ("nflverse", "players"),
        ("nflverse", "player_id_mappings"),
        ("nflverse", "weekly_rosters"),
        ("nflverse", "player_stats_weekly"),
        ("nflverse", "team_stats_weekly"),
        ("nflverse", "pbp"),
        ("nflverse", "snap_counts"),
        ("football", "dim_teams"),
        ("football", "dim_players"),
        ("football", "xref_player_ids"),
        ("football", "fact_games"),
        ("football", "fact_events"),
        ("football", "fact_player_team_weeks"),
        ("football", "fact_player_week_stats"),
        ("football", "fact_team_week_stats"),
        ("football", "fact_snap_counts"),
    ]
    counts: dict[str, int] = {}
    with conn.cursor() as cur:
        for schema, table in tables:
            cur.execute(f"SELECT count(*) FROM {schema}.{table}")
            counts[f"{schema}.{table}"] = cur.fetchone()[0]
    return counts


def validation_queries() -> dict[str, str]:
    return {
        "games_home_teams_missing": """
            SELECT count(*) FROM nflverse.games g
            LEFT JOIN nflverse.teams t ON t.team_abbr = g.home_team
            WHERE g.season = 2024 AND g.home_team IS NOT NULL AND t.team_abbr IS NULL
        """,
        "games_away_teams_missing": """
            SELECT count(*) FROM nflverse.games g
            LEFT JOIN nflverse.teams t ON t.team_abbr = g.away_team
            WHERE g.season = 2024 AND g.away_team IS NOT NULL AND t.team_abbr IS NULL
        """,
        "weekly_roster_teams_missing": """
            SELECT count(*) FROM nflverse.weekly_rosters r
            LEFT JOIN nflverse.teams t ON t.team_abbr = r.team
            WHERE r.team IS NOT NULL AND t.team_abbr IS NULL
        """,
        "player_stats_teams_missing": """
            SELECT count(*) FROM nflverse.player_stats_weekly s
            LEFT JOIN nflverse.teams t ON t.team_abbr = s.team
            WHERE s.team IS NOT NULL AND t.team_abbr IS NULL
        """,
        "team_stats_teams_missing": """
            SELECT count(*) FROM nflverse.team_stats_weekly s
            LEFT JOIN nflverse.teams t ON t.team_abbr = s.team
            WHERE s.team IS NOT NULL AND t.team_abbr IS NULL
        """,
        "pbp_games_missing": """
            SELECT count(*) FROM nflverse.pbp p
            LEFT JOIN nflverse.games g ON g.game_id = p.game_id
            WHERE g.game_id IS NULL
        """,
        "snap_games_missing": """
            SELECT count(*) FROM nflverse.snap_counts s
            LEFT JOIN nflverse.games g ON g.game_id = s.game_id
            WHERE g.game_id IS NULL
        """,
        "player_stats_players_missing": """
            SELECT count(*) FROM nflverse.player_stats_weekly s
            LEFT JOIN nflverse.players p ON p.gsis_id = s.player_id
            WHERE p.gsis_id IS NULL
        """,
        "weekly_roster_players_missing": """
            SELECT count(*) FROM nflverse.weekly_rosters r
            LEFT JOIN nflverse.players p ON p.gsis_id = coalesce(r.gsis_id, r.player_id)
            WHERE p.gsis_id IS NULL
        """,
        "snap_players_missing_by_pfr": """
            SELECT count(*) FROM nflverse.snap_counts s
            LEFT JOIN nflverse.player_id_mappings m
              ON m.provider = 'pfr' AND m.provider_player_id = s.player_id
            WHERE m.provider_player_id IS NULL
        """,
        "model_games_missing_home_teams": """
            SELECT count(*) FROM football.fact_games g
            LEFT JOIN football.dim_teams t ON t.team_abbr = g.home_team
            WHERE g.home_team IS NOT NULL AND t.team_abbr IS NULL
        """,
        "model_games_missing_away_teams": """
            SELECT count(*) FROM football.fact_games g
            LEFT JOIN football.dim_teams t ON t.team_abbr = g.away_team
            WHERE g.away_team IS NOT NULL AND t.team_abbr IS NULL
        """,
        "model_events_missing_games": """
            SELECT count(*) FROM football.fact_events e
            LEFT JOIN football.fact_games g ON g.game_id = e.game_id
            WHERE g.game_id IS NULL
        """,
        "model_player_week_stats_missing_players": """
            SELECT count(*) FROM football.fact_player_week_stats s
            LEFT JOIN football.dim_players p ON p.gsis_id = s.player_id
            WHERE p.gsis_id IS NULL
        """,
        "model_player_week_stats_missing_teams": """
            SELECT count(*) FROM football.fact_player_week_stats s
            LEFT JOIN football.dim_teams t ON t.team_abbr = s.team
            WHERE t.team_abbr IS NULL
        """,
        "model_snap_counts_missing_players": """
            SELECT count(*) FROM football.fact_snap_counts s
            LEFT JOIN football.dim_players p ON p.gsis_id = s.player_id
            WHERE p.gsis_id IS NULL
        """,
        "model_snap_counts_missing_games": """
            SELECT count(*) FROM football.fact_snap_counts s
            LEFT JOIN football.fact_games g ON g.game_id = s.game_id
            WHERE g.game_id IS NULL
        """,
    }


def validate(conn: psycopg.Connection) -> dict[str, Any]:
    checks: dict[str, int] = {}
    with conn.cursor() as cur:
        for name, sql in validation_queries().items():
            cur.execute(sql)
            checks[name] = cur.fetchone()[0]
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "row_counts": table_counts(conn),
        "relationship_failures": checks,
        "passed": all(value == 0 for value in checks.values()),
    }


def write_report(report: dict[str, Any], path: Path = DEFAULT_REPORT) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")


def command_manifest(args: argparse.Namespace) -> None:
    rows = [manifest_row(asset, asset.local_path, "", skipped=False) for asset in selected_assets()]
    print(json.dumps(rows, indent=2, sort_keys=True))


def command_download_samples(args: argparse.Namespace) -> None:
    rows = [download_file(asset) for asset in selected_assets()]
    write_manifest(rows)
    print(f"Downloaded/verified {len(rows)} release assets. Manifest: {DEFAULT_RAW_DIR / 'manifest.json'}")


def command_load_samples(args: argparse.Namespace) -> None:
    global SAMPLE_ROW_LIMIT
    SAMPLE_ROW_LIMIT = args.sample_row_limit
    manifest = read_manifest()
    with connect(args.database_url) as conn:
        create_schema(conn)
        loaded = {loader.__name__.replace("load_", ""): loader(conn, manifest) for loader in LOADERS}
        loaded["derived_snap_player_mappings"] = derive_snap_player_mappings(conn)
        loaded["model_tables"] = sync_model_tables(conn)
        conn.commit()
        report = validate(conn)
    report["loaded_rows_this_run"] = loaded
    write_report(report)
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["passed"]:
        raise SystemExit("Relationship validation failed.")


def command_validate(args: argparse.Namespace) -> None:
    with connect(args.database_url) as conn:
        create_schema(conn)
        report = validate(conn)
    write_report(report)
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["passed"]:
        raise SystemExit("Relationship validation failed.")


def command_build_model_tables(args: argparse.Namespace) -> None:
    with connect(args.database_url) as conn:
        create_schema(conn)
        synced = sync_model_tables(conn)
        conn.commit()
        report = validate(conn)
    report["synced_model_rows"] = synced
    write_report(report)
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["passed"]:
        raise SystemExit("Relationship validation failed.")


def command_test_reimport(args: argparse.Namespace) -> None:
    global SAMPLE_ROW_LIMIT
    SAMPLE_ROW_LIMIT = args.sample_row_limit
    manifest = read_manifest()
    with connect(args.database_url) as conn:
        create_schema(conn)
        for loader in LOADERS:
            loader(conn, manifest)
        derive_snap_player_mappings(conn)
        sync_model_tables(conn)
        conn.commit()
        before = table_counts(conn)
        for loader in LOADERS:
            loader(conn, manifest)
        derive_snap_player_mappings(conn)
        sync_model_tables(conn)
        conn.commit()
        after = table_counts(conn)
        report = validate(conn)
    idempotent = before == after
    report["reimport_before_counts"] = before
    report["reimport_after_counts"] = after
    report["reimport_idempotent"] = idempotent
    write_report(report)
    print(json.dumps(report, indent=2, sort_keys=True))
    if not idempotent or not report["passed"]:
        raise SystemExit("Reimport idempotency or relationship validation failed.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download, load, and validate nflverse release asset samples.")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
        help="PostgreSQL connection URL. Defaults to DATABASE_URL or the local docker-compose database.",
    )
    parser.add_argument(
        "--sample-row-limit",
        type=int,
        default=int(os.environ.get("NFLVERSE_SAMPLE_ROW_LIMIT", DEFAULT_SAMPLE_ROW_LIMIT)),
        help="Rows to load from each high-volume sample asset. Use 0 to load full selected files.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("manifest", help="Print selected release assets from GitHub.")
    subparsers.add_parser("download-samples", help="Download selected Parquet release assets and write a checksum manifest.")
    subparsers.add_parser("load-samples", help="Load downloaded samples into PostgreSQL and validate relationships.")
    subparsers.add_parser("build-model-tables", help="Sync canonical football model tables from loaded nflverse staging tables.")
    subparsers.add_parser("validate", help="Validate already-loaded PostgreSQL sample relationships.")
    subparsers.add_parser("test-reimport", help="Load samples twice and prove row counts do not increase.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    commands = {
        "manifest": command_manifest,
        "download-samples": command_download_samples,
        "load-samples": command_load_samples,
        "build-model-tables": command_build_model_tables,
        "validate": command_validate,
        "test-reimport": command_test_reimport,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import psycopg

from football_data.nflverse import (
    DEFAULT_DATABASE_URL,
    connect,
    create_schema,
    sync_model_tables,
    table_counts,
    validate,
)


TERRAFORM_DIR = Path("infra/postgres")


def run_command(command: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def require_executable(name: str) -> None:
    if shutil.which(name) is None:
        raise SystemExit(f"`{name}` is required for this command but was not found on PATH.")


def terraform_command(args: argparse.Namespace, action: str) -> None:
    require_executable("terraform")
    command = ["terraform", f"-chdir={TERRAFORM_DIR}", action]
    if action in {"apply", "destroy"} and args.auto_approve:
        command.append("-auto-approve")
    run_command(command)


def terraform_output_json() -> dict[str, Any]:
    require_executable("terraform")
    result = run_command(["terraform", f"-chdir={TERRAFORM_DIR}", "output", "-json"], capture=True)
    return json.loads(result.stdout)


def terraform_database_url(fallback: str) -> str:
    try:
        outputs = terraform_output_json()
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
        return fallback
    raw = outputs.get("database_url", {})
    return raw.get("value") or fallback


def wait_for_database(database_url: str, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with connect(database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
                return
        except (psycopg.Error, OSError) as exc:
            last_error = exc
            time.sleep(1)
    raise SystemExit(f"Database did not become ready within {timeout_seconds}s: {last_error}")


def database_url(args: argparse.Namespace) -> str:
    return args.database_url or os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL


def command_url(args: argparse.Namespace) -> None:
    print(database_url(args))


def command_terraform(args: argparse.Namespace) -> None:
    terraform_command(args, args.terraform_action)


def command_up(args: argparse.Namespace) -> None:
    require_executable("terraform")
    run_command(["terraform", f"-chdir={TERRAFORM_DIR}", "init"])
    apply_command = ["terraform", f"-chdir={TERRAFORM_DIR}", "apply"]
    if args.auto_approve:
        apply_command.append("-auto-approve")
    run_command(apply_command)
    url = terraform_database_url(database_url(args))
    wait_for_database(url, args.timeout)
    print(f"Postgres is ready: {url}")


def command_down(args: argparse.Namespace) -> None:
    terraform_command(args, "destroy")


def command_init_schema(args: argparse.Namespace) -> None:
    url = database_url(args)
    wait_for_database(url, args.timeout)
    with connect(url) as conn:
        create_schema(conn)
    print("Applied nflverse staging schema and normalized football model schema.")


def command_build_model(args: argparse.Namespace) -> None:
    url = database_url(args)
    wait_for_database(url, args.timeout)
    with connect(url) as conn:
        create_schema(conn)
        synced = sync_model_tables(conn)
        conn.commit()
    print(json.dumps(synced, indent=2, sort_keys=True))


def command_check(args: argparse.Namespace) -> None:
    url = database_url(args)
    wait_for_database(url, args.timeout)
    with connect(url) as conn:
        create_schema(conn)
        report = validate(conn)
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["passed"]:
        raise SystemExit("Database validation failed.")


def command_counts(args: argparse.Namespace) -> None:
    url = database_url(args)
    wait_for_database(url, args.timeout)
    with connect(url) as conn:
        create_schema(conn)
        counts = table_counts(conn)
    print(json.dumps(counts, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage the FootballAnalytics Postgres database.")
    parser.add_argument(
        "--database-url",
        default=None,
        help="PostgreSQL connection URL. Defaults to DATABASE_URL or the local football/football database.",
    )
    parser.add_argument("--timeout", type=int, default=60, help="Seconds to wait for Postgres readiness.")

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("url", help="Print the database URL used by the CLI.")

    up_parser = subparsers.add_parser("up", help="Run Terraform init/apply and wait for Postgres.")
    up_parser.add_argument("--auto-approve", action="store_true", help="Pass -auto-approve to Terraform apply.")

    down_parser = subparsers.add_parser("down", help="Run Terraform destroy.")
    down_parser.add_argument("--auto-approve", action="store_true", help="Pass -auto-approve to Terraform destroy.")

    terraform_parser = subparsers.add_parser("terraform", help="Run a Terraform action in infra/postgres.")
    terraform_parser.add_argument("terraform_action", choices=["init", "plan", "apply", "destroy", "output"])
    terraform_parser.add_argument("--auto-approve", action="store_true", help="Pass -auto-approve to apply/destroy.")

    subparsers.add_parser("init-schema", help="Create nflverse staging and normalized football schemas.")
    subparsers.add_parser("build-model", help="Sync normalized football model tables from nflverse staging data.")
    subparsers.add_parser("check", help="Validate database relationships.")
    subparsers.add_parser("counts", help="Print staging and model table row counts.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    commands = {
        "url": command_url,
        "up": command_up,
        "down": command_down,
        "terraform": command_terraform,
        "init-schema": command_init_schema,
        "build-model": command_build_model,
        "check": command_check,
        "counts": command_counts,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()

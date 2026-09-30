# FootballAnalytics

FootballAnalytics is a local-first NFL analytics backend. It ingests nflverse
release assets, stores source data in PostgreSQL, and builds normalized,
model-ready football tables for analytics, forecasting and product features.

## What This Builds

The project uses **nflverse/nflverse-data** as the primary post-game batch feed.

Data flows through two PostgreSQL schemas:

```text
nflverse release assets
        -> data/raw/nflverse/*.parquet
        -> nflverse staging tables
        -> football normalized model tables
```

- `nflverse`: source-preserving staging tables.
- `football`: normalized model-ready dimensions, facts and ID mappings.

Schema docs:

- [nflverse data feed](docs/nflverse-data.md)
- [core football schema](docs/core-football-schema.md)
- [machine-readable schema contract](schema/core_football_schema.json)
- [issue implementation map](docs/issues.md)

## Prerequisites

You need:

- Docker Desktop, with the Docker daemon running
- Terraform
- `uv`
- Git

### macOS

Install command-line tools:

```sh
brew install uv terraform
```

Install Docker Desktop for Mac from Docker, open it, and wait until Docker is
running.

Check your tools:

```sh
uv --version
terraform version
docker version
```

### Windows WSL

Use WSL 2 with Ubuntu or another Linux distribution.

Install Docker Desktop for Windows, then enable WSL integration:

1. Open Docker Desktop.
2. Go to Settings.
3. Open Resources -> WSL Integration.
4. Enable integration for your WSL distribution.
5. Apply and restart Docker Desktop if prompted.

Inside WSL, install the command-line tools:

```sh
sudo apt-get update
sudo apt-get install -y curl unzip git
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Restart your WSL shell or source your shell profile, then install Terraform:

```sh
wget -O- https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(. /etc/os-release && echo "$VERSION_CODENAME") main" | sudo tee /etc/apt/sources.list.d/hashicorp.list
sudo apt-get update
sudo apt-get install -y terraform
```

Check your tools inside WSL:

```sh
uv --version
terraform version
docker version
```

Run this project from the Linux filesystem, such as
`~/code/FootballAnalytics`, rather than from `/mnt/c/...`. Docker and file I/O
are much faster that way.

## Setup From Scratch

Run these from the repository root.

1. Start the local Postgres container:

```sh
uv run --python 3.12 football-db up --auto-approve
```

2. Create the database schemas:

```sh
uv run --python 3.12 football-db init-schema
```

3. Download sample nflverse release assets:

```sh
uv run --python 3.12 nflverse download-samples
```

4. Load staging and model tables:

```sh
uv run --python 3.12 nflverse load-samples
```

5. Validate the database:

```sh
uv run --python 3.12 football-db check
```

If the final command passes, the local backend database is ready.

For the full verification path, also run:

```sh
uv run --python 3.12 nflverse test-reimport
```

## Database Connection

Default local database URL:

```text
postgresql://football:football@localhost:5432/football_analytics
```

Use any SQL client with:

```text
host: localhost
port: 5432
database: football_analytics
user: football
password: football
```

For a different database, set `DATABASE_URL`:

```sh
export DATABASE_URL="postgresql://user:password@host:5432/football_analytics"
```

## Common Commands

Show the database URL used by the CLI:

```sh
uv run --python 3.12 football-db url
```

Show table row counts:

```sh
uv run --python 3.12 football-db counts
```

Rebuild normalized model tables from loaded staging data:

```sh
uv run --python 3.12 football-db build-model
```

Verify reimporting data does not create duplicates:

```sh
uv run --python 3.12 nflverse test-reimport
```

Check GitHub release metadata and download only changed or missing sample
assets:

```sh
uv run --python 3.12 nflverse sync-samples
```

Sync changed assets and load them into Postgres:

```sh
uv run --python 3.12 nflverse sync-samples --load
```

## Scheduled Updates

The repository includes a GitHub Actions workflow at
[.github/workflows/nflverse-sync.yml](.github/workflows/nflverse-sync.yml).

It runs at fixed UTC times:

- every day at `13:00 UTC`
- every Thursday at `15:00 UTC` for the stat-correction check

To enable it, add a repository secret named `DATABASE_URL` with a Postgres
connection string for the database you want the scheduled job to update.

You can also run it manually from GitHub Actions. The manual run includes a
`force_load` option to load even when no changed assets are detected.

For a local fixed-time schedule, add a cron entry on the machine that has access
to your database:

```cron
0 9 * * * cd /path/to/FootballAnalytics && mkdir -p logs && uv run --python 3.12 nflverse sync-samples --load >> logs/nflverse-sync.log 2>&1
0 11 * * 4 cd /path/to/FootballAnalytics && mkdir -p logs && uv run --python 3.12 nflverse sync-samples --load >> logs/nflverse-sync.log 2>&1
```

Stop and remove the Terraform-managed Postgres container:

```sh
uv run --python 3.12 football-db down --auto-approve
```

## Terraform

Terraform files live in [infra/postgres](infra/postgres).

The `football-db` CLI wraps the normal Terraform commands, but you can also run
them directly:

```sh
terraform -chdir=infra/postgres init
terraform -chdir=infra/postgres plan
terraform -chdir=infra/postgres apply
terraform -chdir=infra/postgres destroy
```

Local Terraform state and `terraform.tfvars` are ignored by git.

## Troubleshooting

If `football-db up` cannot connect to Docker, open Docker Desktop and wait for
the daemon to finish starting.

If port `5432` is already in use, copy
[infra/postgres/terraform.tfvars.example](infra/postgres/terraform.tfvars.example)
to `infra/postgres/terraform.tfvars` and change `host_port`.

If Python dependencies are missing, run any `uv run ...` command again. `uv`
creates and manages the local virtual environment automatically.

If Terraform is missing, install it and rerun:

```sh
brew install terraform
```

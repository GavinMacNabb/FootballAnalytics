# FootballAnalytics

Proof-of-concept football analytics workspace for NFL data ingestion, normalized
PostgreSQL storage and model-ready football tables.

## What This Builds

The project uses **nflverse/nflverse-data** as a post-game batch feed.

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

Install these first:

- Docker Desktop, with the Docker daemon running
- Terraform
- `uv`

On macOS with Homebrew:

```sh
brew install uv terraform
```

Install Docker Desktop from Docker, open it, and wait until it says Docker is
running.

Check your tools:

```sh
uv --version
terraform version
docker version
```

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

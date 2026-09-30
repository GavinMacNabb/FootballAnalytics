# Terraform Postgres

This Terraform project provisions a local PostgreSQL container for the football
analytics backend.

It creates:

- a Postgres Docker container
- a dedicated Docker network
- a named Docker volume for persistent database data
- a health check using `pg_isready`

## Commands

From the repository root:

```sh
uv run --python 3.12 football-db up
uv run --python 3.12 football-db init-schema
uv run --python 3.12 football-db check
```

Or run Terraform directly:

```sh
terraform -chdir=infra/postgres init
terraform -chdir=infra/postgres apply
terraform -chdir=infra/postgres destroy
```

Use `terraform.tfvars` to override defaults. Do not commit real credentials or
Terraform state files.

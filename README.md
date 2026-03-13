# PGMind GitHub Action

Run **PostgreSQL diagnostics and operational checks** directly in your CI pipeline.

`pgmind-action` allows teams to detect database risks early by running deterministic PostgreSQL checks during pull requests, deployments, and scheduled workflows.

Built for **DataOps**, **DBRE**, and **platform engineering teams**.

---

# What is PGMind

PGMind is a PostgreSQL diagnostics engine that detects operational risks such as:

- autovacuum drift
- long-running queries
- locking contention
- misconfigured statistics
- database security risks

Instead of manual investigation, teams can run deterministic checks and obtain actionable insights automatically.

---

# Why use it in CI

Database problems often appear as small signals before incidents happen.

Running `pgmind` in CI enables teams to:

- detect performance regressions
- validate database configuration
- monitor operational signals
- standardize DBRE checks
- add database diagnostics to pull requests

---

# Quick Start

Add the action to your workflow:

```yaml
name: Database Diagnostics

on:
  pull_request:
  workflow_dispatch:

jobs:
  pgmind-check:
    runs-on: ubuntu-latest

    steps:
      - name: Run PGMind diagnostics
        uses: labs-ohana/pgmind-action@v1
        with:
          database_url: ${{ secrets.DATABASE_URL }}

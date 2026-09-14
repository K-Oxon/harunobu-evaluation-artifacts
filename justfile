set shell := ["bash", "-euo", "pipefail", "-c"]
export UV_CACHE_DIR := env_var_or_default("UV_CACHE_DIR", ".uv-cache")
export MPLCONFIGDIR := env_var_or_default("MPLCONFIGDIR", ".matplotlib-cache")
export SOURCE_DATE_EPOCH := env_var_or_default("SOURCE_DATE_EPOCH", "1789344000")

default:
    @just --list

# Build paper tables and figures from tracked results without network access.
build-paper-assets:
    uv run python figures/build_tables.py
    uv run python figures/fig-iou-hist.py
    uv run python figures/fig-rule-pass.py
    uv run python figures/fig-strata-heatmap.py

# Download and replay the frozen 600-file e-Stat evaluation (AI-OFF only).
reproduce-estat:
    uv run python -m scripts.estat.replay
    uv run python -m scripts.estat.build_scoring_dir
    uv run python -m scripts.rule_scoring
    uv run python -m scripts.estat.chapter4_evidence all --c1 results/estat/rulescore-tier1-replay.json
    cmp results/chapter4-evidence/file-rule-states.csv results/estat/file-rule-states.csv

# Fetch third-party data and replay both layout evaluations.
reproduce-layout:
    uv run python -m scripts.fetch_layout_data
    uv run python -m scripts.convert_tablesense
    uv run python -m scripts.eval --dataset deco --n 999999 --out results/layout/eval-deco-replay.json
    uv run python -m scripts.eval --dataset tablesense --n 999999 --out results/layout/eval-tablesense-replay.json
    uv run python -m scripts.score_sensitivity --part inject --out results/layout/score-sensitivity-injection-replay.json
    uv run python -m scripts.score_sensitivity --part realdata --results results/layout/eval-deco-replay.json --out results/layout/score-sensitivity-realdata-replay.json

# Repository checks plus deterministic paper-asset regeneration. No test suite is run.
verify:
    uv sync --frozen
    uv run cffconvert --validate
    uv run python scripts/verify.py
    just build-paper-assets
    uv run python scripts/verify.py
    git diff --exit-code -- figures/tables

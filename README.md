# copilot-history-memory-mart

🧠 **Transform your Copilot interactions into organized, actionable knowledge.**

This tool analyzes your Copilot activity history and creates a structured "Memory Mart" - a intelligent knowledge base that learns from your conversations. It automatically categorizes insights, builds connections between related topics, and distills your interactions into foundational beliefs, practical notes, and reference materials.

**Key Features:**
- 📊 **Smart Organization**: Automatically sorts your Copilot conversations into a tiered knowledge system
- 🔗 **Intelligent Linking**: Builds an ontology that connects related topics and insights  
- 📝 **Clean Output**: Generates a single, skimmable OneDoc with all your key learnings
- 🔒 **Privacy-First**: Keeps your data local with git-safe defaults and Docker support
- ⚡ **Zero Config**: Works out-of-the-box with sensible defaults


## How it organizes info (at a glance)

- Tiers
  - Tier 0: Foundational beliefs (short, synthesized, stable). Human-curated anchors.
  - Tier 1: Anchors from real interactions that reinforce Tier 0.
  - Tier 2: Practical notes worth remembering (constraints, practices).
  - Tier 3: Reference snippets grouped by topic; capped per topic in outputs.
- Ontology
  - values: Tier 0/1 items (with IDs) used as anchors for linking.
  - categories: Topic buckets (curated or auto: “auto-<slug>”).
  - map: topic label → category slug.
  - value_map: category slug → related Tier 0/1 value IDs.
  - seeds file: `memory_artifacts/ontology_sources.json` stores categories, aliases, patterns, authors, and accumulated sources.

## Quick start (Windows PowerShell)

```powershell
# 1) Point to your history CSV (already in repo by default)
$env:HISTORY_CSV = "A:/Padawan_Workspace/MP/copilot-activity-history.csv"

# 2) Compact run (default): OneDoc + cross-reference only
$env:COMPACT_MODE = "1"            # default
$env:ONTOLOGY_BUILD = "0"          # reuse ontology.json
$env:ONTOLOGY_SUGGEST = "0"        # keep suggestions off (clean)
$env:ONTOLOGY_AUTO_APPLY = "0"     # do not auto-apply suggestions
$env:ONTOLOGY_SOURCES_SUGGEST = "0"# disable sources suggestions

A:/Padawan_Workspace/MP/.venv/Scripts/python.exe A:/Padawan_Workspace/MP/memory_artifacts/pipeline.py
```

Outputs (compact mode):
- memory_artifacts/final/Memory_Mart_OneDoc.md — single, skimmable deliverable
- memory_artifacts/final/cross_reference.md — Tier 2/3 entries → categories → Tier 0/1 links

Optional ontology build (deterministic):
```powershell
$env:ONTOLOGY_BUILD = "1"
A:/Padawan_Workspace/MP/.venv/Scripts/python.exe A:/Padawan_Workspace/MP/memory_artifacts/pipeline.py
```
Additional outputs when building ontology:
- memory_artifacts/ontology.json — current ontology (values, categories, map, value_map)
- memory_artifacts/final/ontology_build_log.md — audit log (mapping rules, value_map, top sources)
- memory_artifacts/ontology_sources.json — editable seeds and accumulated sources/authors

## Where to get copilot-activity-history.csv

- Official export (Microsoft Privacy):
  - Visit https://account.microsoft.com/privacy/copilot
  - Sign in with the same Microsoft account you use with Copilot.
  - In "Your Copilot activity history", choose "Export all activity history".
  - Download the export. If the file name differs, you can rename it to `copilot-activity-history.csv` for convenience.
  - Note: UI wording and download format may evolve; the entry point is the Microsoft Privacy portal under Copilot.

- Default location: this repo expects the file at the repo root as `copilot-activity-history.csv`. It’s ignored by git for privacy.
- Custom location: point the pipeline to any path via the `HISTORY_CSV` env var.

Examples (Windows PowerShell):

```powershell
# CSV in repo root
$env:HISTORY_CSV = "${PWD}/copilot-activity-history.csv"

# CSV elsewhere on disk
$env:HISTORY_CSV = "D:/exports/copilot-activity-history.csv"
```

How to obtain the CSV (alternatives):
- If you keep your own logs, any CSV with columns similar to timestamp/prompt/response/source will work; the pipeline is lenient and ignores unknown columns.
- You can also generate a minimal CSV manually for testing (a few rows) and iterate from there.

## Run in Docker

Build the image (from repo root):

```powershell
docker build -t copilot-history-memory-mart:dev .
```

Run with your local CSV mounted and outputs written to a local folder:

```powershell
# Create an outputs folder on host (optional)
mkdir -Force .\out | Out-Null

docker run --rm ^
  -e COMPACT_MODE=1 -e ONTOLOGY_BUILD=1 ^
  -e HISTORY_CSV=/data/copilot-activity-history.csv ^
  -e MEM_OUT_DIR=/app/memory_artifacts ^
  -v ${PWD}/copilot-activity-history.csv:/data/copilot-activity-history.csv:ro ^
  -v ${PWD}/memory_artifacts:/app/memory_artifacts ^
  copilot-history-memory-mart:dev
```

Notes:
- If you don’t mount `memory_artifacts`, the container writes inside the image layer; mounting makes outputs visible and reusable.
- You can also mount a different output dir and set `MEM_OUT_DIR` accordingly.

Stop containers (cleanup):

```powershell
# Stop all running containers (if any)
$ids = docker ps -q; if ($ids) { docker stop $ids }

# List all containers and statuses
docker ps -a --format "table {{.ID}}`t{{.Image}}`t{{.Status}}`t{{.Names}}"
```

Privacy defaults:
- `.gitignore` and `.dockerignore` exclude personal/generated data (CSV, ontology.json, ontology_sources.json, final/ outputs).
- The pipeline auto-creates a minimal seeds file if missing so you don’t need to publish private JSON.

## Flags (environment variables)
- COMPACT_MODE: 1 to write only OneDoc + cross_reference (default). Set 0 to emit extra intermediate files.
- ONTOLOGY_BUILD: 1 to rebuild ontology.json and audit log from data + seeds; 0 to reuse existing ontology.json.
- ONTOLOGY_SUGGEST: 1 to emit Tier 2/3–derived ontology suggestions (off by default to avoid clutter).
- ONTOLOGY_AUTO_APPLY: 1 to auto-merge suggestions into ontology.json (use with care).
- ONTOLOGY_SOURCES_SUGGEST: 1 to emit sources_suggestions.md (gated off by default).

## Inputs
- copilot-activity-history.csv — your exported Copilot interactions; the pipeline treats this as the source of truth.
- memory_artifacts/ontology_sources.json — human-editable seeds: categories, aliases, patterns, sources, authors.

Tip: After manual edits to `ontology_sources.json`, run with `ONTOLOGY_BUILD=1` once to sync ontology.json and the audit log.

## Editing the seeds (ontology_sources.json)
Key sections:
- categories: slug → { label, description, aliases[], wiki_refs[] }
- aliases: label/alias (lowercase) → category slug
- patterns: regex → category slug (for topic auto-routing)
- authors: [{ name, subjects[], isbns[], book_patterns[] }]

Small, safe edits that help immediately:
- Add a missing alias for a recurring topic label
- Add a simple regex pattern (e.g., "dishwasher|rinse aid|salt|siemens" → dishwasher-tips)
- Add an author with known ISBNs to improve source linking

## Troubleshooting
- OneDoc didn’t update
  - Ensure you’re running the pipeline from the virtual env and that COMPACT_MODE is set (or unset—it defaults to 1).
  - The writer overwrites `memory_artifacts/final/Memory_Mart_OneDoc.md` each run.
- Ontology didn’t change after editing seeds
  - Set `$env:ONTOLOGY_BUILD = "1"` for one run; the builder reads your edited seeds and writes a fresh `ontology.json` with an audit log.
- Too many files
  - Keep COMPACT_MODE=1 and suggestions flags at 0. This outputs only OneDoc, cross_reference, and (if building) the audit log.

## Make it better
- Curate `ontology_sources.json`: add/merge aliases and patterns for your most common topics; add a few key authors.
- Tune thresholds: if you want more/less aggressive value_map linking, adjust token overlap thresholds in the builder later.
- Schedule periodic runs (Task Scheduler) with `ONTOLOGY_BUILD=1` weekly and compact mode on.
- Add light tests for topic routing and value linking if you expand heuristics.

## Repository layout
- memory_artifacts/pipeline.py — main ETL, synthesis, and writers
- memory_artifacts/ontology_builder.py — deterministic ontology builder + sources accumulation
- memory_artifacts/ontology.json — built ontology (values, categories, map, value_map)
- memory_artifacts/ontology_sources.json — seeds + accumulated sources/authors (human-editable)
- memory_artifacts/final/ — OneDoc, cross_reference, ontology_build_log

```text
A:/Padawan_Workspace/MP/
  ├─ copilot-activity-history.csv
  └─ memory_artifacts/
       ├─ pipeline.py
       ├─ ontology_builder.py
       ├─ ontology.json
       ├─ ontology_sources.json
       └─ final/
            ├─ Memory_Mart_OneDoc.md
            ├─ cross_reference.md
            └─ ontology_build_log.md
```

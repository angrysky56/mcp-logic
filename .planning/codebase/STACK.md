---
last_mapped: 2026-05-01
focus: tech
---

# Tech Stack — mcp-logic

## Language & Runtime

| Item | Value |
|---|---|
| **Language** | Python 3.10+ (requires-python = ">=3.10") |
| **Runtime (dev)** | Python 3.13 (`.venv`) |
| **Runtime (Docker)** | Python 3.12-slim |
| **Packaging** | `hatchling` (PEP 517 build backend) |
| **Env management** | `uv` venv (`.venv/`), Docker (`docker-env/`) |

## Core Dependencies

| Package | Version | Role |
|---|---|---|
| `mcp` | >=1.0.0 | Model Context Protocol SDK (stdio server + types) |
| `pydantic` | >=2.0.0 | Data validation (transitively used by `mcp`) |

> **No other runtime dependencies** in `pyproject.toml`. All logic is implemented in-house.

## Standard Library Modules Used

- `asyncio` — async MCP server loop
- `subprocess` — spawn `prover9` and `mace4` binaries
- `tempfile` / `os` — create/clean temp input files
- `pathlib` — cross-platform binary path resolution
- `re`, `itertools`, `math`, `dataclasses` — core logic modules
- `argparse` — CLI entry point argument parsing
- `logging` — structured DEBUG/INFO/ERROR logging throughout

## External Binary Dependencies (Not Python)

| Binary | Source | Location |
|---|---|---|
| `prover9` | LADR (laitep/ladr on GitHub) | `ladr/bin/prover9` |
| `mace4` | LADR | `ladr/bin/mace4` |

Both are compiled C programs from the Argonne/LADR project. The Python layer wraps them via `subprocess.run()`. The setup scripts (`linux-setup-script.sh`, `windows-setup-mcp-logic.bat`) download and build these automatically from source using CMake.

## Build System

- **`pyproject.toml`** — full project definition (PEP 621)
- **`hatchling`** — wheel builder, sources from `src/mcp_logic`
- **Entry point**: `mcp_logic = "mcp_logic.server:cli"` → `mcp_logic` CLI command
- **Dockerfile** — Python 3.12-slim base; uses `pip install uv`, then `uv venv`, then `pip install -e .`

## Linting & Code Quality (Trunk.io)

Managed via `.trunk/trunk.yaml` (Trunk v0.1):

| Tool | Version | Purpose |
|---|---|---|
| `ruff` | 0.15.12 | Fast Python linter + formatter |
| `black` | 26.3.1 | Python formatter |
| `isort` | 8.0.1 | Import sorting |
| `bandit` | 1.9.4 | Security analysis |
| `hadolint` | 2.14.0 | Dockerfile linting |
| `checkov` | 3.2.526 | IaC security scanning |
| `markdownlint` | 0.48.0 | Markdown style |
| `yamllint` | 1.38.0 | YAML validation |
| `trufflehog` | 3.95.2 | Secret scanning |
| `prettier` | 3.8.3 | General formatter |
| `shellcheck` / `shfmt` | — | Shell script linting/formatting |

Config file: `.trunk/configs/ruff.toml`

## Testing

- **Framework**: `pytest`
- **Config**: `[tool.pytest.ini_options]` in `pyproject.toml`, `testpaths = ["tests"]`
- **Test count**: 6 test files, ~30+ test functions
- **Coverage**: HCC prover (unit), VFE engine (unit), formula AST (unit), integration (component-level)

## MCP Protocol

- **Transport**: `stdio` (stdin/stdout JSON-RPC)
- **SDK**: `mcp.server.stdio`, `mcp.server.Server`, `mcp.types`
- **Server name**: `"logic-manager"` (internal) / `"logic"` (exported in `InitializationOptions`)
- **Version**: `"0.2.0"` (server_version)

## Deployment / Integration

- **Claude Desktop**: JSON MCP server config using `uv --directory … run mcp_logic --prover-path …`
- **Docker**: `Dockerfile` exposes ports 8888-8892 (though MCP uses stdio, not HTTP)
- **Direct run**: `run_mcp_logic.sh` / `run_mcp_logic.bat`

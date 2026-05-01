---
last_mapped: 2026-05-01
focus: quality
---

# Conventions — mcp-logic

## Code Style

- **Formatter**: `black` (via Trunk)
- **Linter**: `ruff` (Trunk config at `.trunk/configs/ruff.toml`)
- **Import order**: `isort` enforced
- **Security**: `bandit` (annotates trunk-ignore comments where needed)
- **Type hints**: Used throughout on all public functions and class methods
- **Docstrings**: Google style, present on all public classes and methods

### Example Function Signature Pattern

```python
def find_model(
    self, premises: List[str], domain_size: Optional[int] = None
) -> Dict[str, Any]:
    """Find a model that satisfies the given premises

    Args:
        premises: List of logical premises
        domain_size: Specific domain size, or None to search incrementally

    Returns:
        Result dictionary with model if found
    """
```

## Dataclass Patterns

Immutable frozen dataclasses are used throughout for results and AST nodes:

```python
@dataclass(frozen=True, slots=True)   # AST nodes (formula_ast.py)
class Var:
    name: str

@dataclass(frozen=True)               # Result types (hcc_prover.py, vfe_engine.py)
class ContingencyResult:
    is_contingent: bool
    proof_trace: List[ProofStep]
    ...
```

- **AST nodes** use both `frozen=True` AND `slots=True` for performance
- **Result types** use `frozen=True` only (no slots, contain mutable containers like `List`)

## Import Style

- Standard library first, then third-party, then internal
- Explicit imports (no `import *`)
- `from __future__ import annotations` used in modules with forward references (`hcc_prover.py`, `vfe_engine.py`, `formula_ast.py`)
- Internal imports use package-relative: `from mcp_logic.formula_ast import parse`

```python
# Standard pattern in server.py:
import argparse
import asyncio
import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import mcp.server.stdio
import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from mcp_logic.categorical_helpers import CategoricalHelpers, group_axioms, monoid_axioms
from mcp_logic.hcc_prover import check_contingency
from mcp_logic.mace4_wrapper import Mace4Wrapper
from mcp_logic.syntax_validator import validate_formulas
from mcp_logic.vfe_engine import abductive_explain
```

## Logging Pattern

```python
# Module-level logger setup:
logging.basicConfig(level=logging.DEBUG)          # server.py
logger = logging.getLogger("mcp_logic")           # server.py
logger = logging.getLogger("mcp_logic.mace4")     # mace4_wrapper.py

# Usage patterns:
logger.debug("Created input file content:\n%s", input_content)  # %-style formatting
logger.info("Starting Logic MCP Server with Prover9/Mace4 at: %s", prover_path)
logger.warning("Mace4 not available: %s", e)
logger.error("Proof search timed out after %d seconds", timeout)
logger.error("Tool error: %s", e, exc_info=True)  # exc_info=True for stack traces
```

## Error Handling Patterns

### Subprocess Calls

All subprocess calls follow this pattern:
```python
try:
    result = subprocess.run([...], capture_output=True, text=True, timeout=timeout, check=False)
    # Parse stdout for expected patterns
except subprocess.TimeoutExpired:
    return {"result": "timeout", "reason": f"...exceeded {timeout} seconds"}
except (subprocess.SubprocessError, OSError, ValueError) as e:
    logger.error("...: %s", e)
    return {"result": "error", "reason": str(e)}
finally:
    try:
        input_path.unlink()
    except (FileNotFoundError, PermissionError, OSError):
        pass  # Temp file cleanup failed, not critical
```

### Tool-level Error Handling (server.py)

```python
try:
    # tool logic
except (KeyError, ValueError, RuntimeError) as e:
    logger.error("Tool error: %s", e, exc_info=True)
    return [types.TextContent(type="text", text=json.dumps({"error": str(e), "type": type(e).__name__}))]
```

### Validation-first Pattern

The `prove` tool validates syntax before running the prover:
```python
validation = validate_formulas(all_formulas)
if not validation["valid"]:
    return [types.TextContent(type="text", text=json.dumps({"result": "syntax_error", "validation": validation}))]
```

## Return Value Convention

All tool handlers return `list[types.TextContent]` with `text=json.dumps(result, indent=2)`.

All internal function return dicts with a `"result"` key:
- `"proved"` / `"unprovable"` / `"refuted"` / `"error"` / `"timeout"` / `"syntax_error"` — Prover9
- `"model_found"` / `"no_model_found"` / `"error"` / `"timeout"` / `"unknown"` — Mace4

## Binary Path Resolution

Cross-platform pattern (try Linux/Mac binary first, then `.exe`):
```python
self.prover_exe = self.prover_path / "prover9.exe"
if not self.prover_exe.exists():
    self.prover_exe = self.prover_path / "prover9"
    if not self.prover_exe.exists():
        raise FileNotFoundError(f"Prover9 not found at {self.prover_exe} or with .exe extension")
```

## Trunk Ignore Annotations

`bandit` false-positives for string constants are suppressed with:
```python
# trunk-ignore(bandit/B105)
_TOKEN_VAR = "VAR"
```

## File Organization Philosophy

- **One class/concept per file** (with minor exceptions like convenience functions in `categorical_helpers.py`)
- **Formula AST is the foundation** — no internal imports, used by everything else
- **Validation is a pre-flight concern** — `syntax_validator.py` is called before any subprocess
- **External wrappers are separate** — `mace4_wrapper.py` isolated from main server

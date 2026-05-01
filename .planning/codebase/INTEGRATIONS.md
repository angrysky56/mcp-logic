---
last_mapped: 2026-05-01
focus: tech
---

# Integrations — mcp-logic

## External Binaries (Primary Integration)

### Prover9 (FOL Theorem Prover)

- **What**: First-order logic resolution prover from the LADR library by William McCune
- **How**: `subprocess.run([str(self.prover_exe), "-f", str(input_path)])`, stdout parsed for `"THEOREM PROVED"` / `"SEARCH FAILED"` / `"Fatal error"`
- **Input format**: Prover9 `.in` file format (TPTP-like):

  ```
  formulas(assumptions).
    all x (man(x) -> mortal(x)).
    man(socrates).
  end_of_list.

  formulas(goals).
    mortal(socrates).
  end_of_list.
  ```

- **Binary path**: Resolved at startup from `--prover-path` CLI arg → `{path}/prover9` or `{path}/prover9.exe`
- **CWD**: Set to the binary's parent directory during subprocess call
- **Timeout**: 60 seconds hardcoded
- **Managed by**: `src/mcp_logic/server.py` `LogicEngine` class, `_create_input_file()` + `_run_prover()`

### Mace4 (Finite Model Finder)

- **What**: Finite model finder / counterexample searcher from the LADR library
- **How**: `subprocess.run([str(self.mace4_exe), "-f", str(input_path)])`, stdout parsed for `"DOMAIN SIZE"` + `"interpretation("` (model found) vs `"SEARCH FAILED"/"SEARCH TERMINATED"`
- **Input format**: Same Mace4 format with `assign()` directives + `formulas(assumptions).` + optional `formulas(goals).` (Mace4 auto-negates the goal internally)
  ```
  assign(domain_size, 2).
  assign(end_size, 10).
  assign(max_seconds, 60).
  formulas(assumptions).
    P(a).
  end_of_list.
  formulas(goals).
    P(b).
  end_of_list.
  ```
- **Binary path**: `{prover_path}/mace4` or `{prover_path}/mace4.exe`
- **Incremental search**: Default range domain_size=2 to end_size=10
- **Managed by**: `src/mcp_logic/mace4_wrapper.py` `Mace4Wrapper` class

## MCP Protocol (Client Integration)

- **Protocol**: Model Context Protocol (MCP) over stdio JSON-RPC
- **SDK**: `mcp>=1.0.0` Python package
- **Client compatibility**: Claude Desktop (primary), any MCP-compliant host
- **Tool registration**: `@server.list_tools()` decorator returns 8 tool schemas
- **Tool invocation**: `@server.call_tool()` dispatcher handles requests

### 8 Exposed MCP Tools

| Tool Name              | Handler Location             | External Call                          |
| ---------------------- | ---------------------------- | -------------------------------------- |
| `prove`                | `server.py:handle_call_tool` | Prover9 or HCC (propositional routing) |
| `check_well_formed`    | `server.py:handle_call_tool` | None (pure Python)                     |
| `find_model`           | `server.py:handle_call_tool` | Mace4                                  |
| `find_counterexample`  | `server.py:handle_call_tool` | Mace4                                  |
| `verify_commutativity` | `server.py:handle_call_tool` | None (returns FOL for `prove`)         |
| `get_category_axioms`  | `server.py:handle_call_tool` | None (pure Python)                     |
| `check_contingency`    | `server.py:handle_call_tool` | None (HCC pure Python)                 |
| `abductive_explain`    | `server.py:handle_call_tool` | None (VFE pure Python)                 |

## No External HTTP/API Integrations

There are **no HTTP clients, no REST APIs, no cloud services, no databases** in this project. All logic is either:

1. Delegated to local LADR binaries (Prover9/Mace4)
2. Implemented in pure Python (HCC, VFE, AST, Syntax validation)

## Temp File System Usage

Both `LogicEngine` and `Mace4Wrapper` create temp files via `tempfile.mkstemp(suffix=".in", text=True)` for each call, and clean them up in a `finally` block. This is the only significant I/O side-effect at runtime.

## LADR Source Integration (Build Time)

- The `ladr/` subdirectory is a checkout/build of the [laitep/ladr](https://github.com/laitep/ladr) repository
- Built using CMake (`ladr/CMakeLists.txt`, `ladr/build/`)
- Output: `ladr/bin/prover9` and `ladr/bin/mace4` native executables
- `ladr/` is NOT a Python package; it's a compiled C library project

## GitHub (CI / Funding)

- `.github/FUNDING.yml` — GitHub Sponsors config
- No GitHub Actions CI workflows present (gap — see CONCERNS.md)

---
last_mapped: 2026-05-01
focus: arch
---

# Structure — mcp-logic

## Root Directory Layout

```
mcp-logic/
├── src/
│   └── mcp_logic/           # ← Main Python package (src-layout)
│       ├── __main__.py      # Module entry point (python -m mcp_logic)
│       ├── server.py        # MCP server, LogicEngine, tool handlers (589 lines)
│       ├── mace4_wrapper.py # Mace4 model finder wrapper (258 lines)
│       ├── hcc_prover.py    # HCC propositional prover (210 lines)
│       ├── formula_ast.py   # Propositional AST + parser + utilities (413 lines)
│       ├── vfe_engine.py    # VFE abductive reasoning engine (143 lines)
│       ├── categorical_helpers.py  # Category theory FOL generation (179 lines)
│       └── syntax_validator.py     # Pre-flight formula validator (215 lines)
│
├── tests/                   # Test suite
│   ├── __init__.py
│   ├── test_hcc_prover.py   # HCC prover unit tests (152 lines, ~20 tests)
│   ├── test_vfe_engine.py   # VFE engine unit tests (97 lines, ~8 tests)
│   ├── test_formula_ast.py  # Formula AST unit tests
│   ├── test_enhancements.py # Component integration tests (110 lines)
│   ├── test_proofs.py       # Integration tests (48 lines, Prover9-dependent)
│   ├── test_debug.py        # Debug helpers
│   └── debug_mace4.py       # Manual Mace4 debug script
│
├── ladr/                    # LADR C library source + build
│   ├── bin/                 # Compiled binaries: prover9, mace4
│   │   └── README.md
│   ├── ladr/                # C source for LADR library
│   ├── provers.src/         # Prover9 C source
│   ├── mace4.src/           # Mace4 C source
│   ├── apps.src/            # LADR apps C source
│   ├── build/               # CMake build artifacts
│   ├── CMakeLists.txt
│   └── README.md
│
├── .venv/                   # Python virtual environment (Python 3.13)
├── docker-env/              # Docker-specific venv (Python 3.12) — legacy
│
├── Documents/               # Human documentation / analysis
│   └── KnowledgeToApplication.md
│
├── .handoff_docs/           # AI context handoff docs
│   ├── codebaseDetails.md
│   ├── errorHandling.md
│   ├── handoff_notes.md
│   ├── integrationGuides.md
│   ├── techStack.md
│   └── workflowDetails.md
│
├── .trunk/                  # Trunk.io linter configuration
│   ├── trunk.yaml
│   └── configs/
│       ├── ruff.toml
│       ├── .hadolint.yaml
│       ├── .markdownlint.yaml
│       └── .yamllint.yaml
│
├── .github/
│   └── FUNDING.yml          # GitHub Sponsors config
│
├── .serena/
│   └── project.yml          # Serena AI project config
│
├── pyproject.toml           # Project metadata, deps, build config
├── Dockerfile               # Docker build definition
├── mcp_config.json          # Template MCP server config
├── mcp_logic_agent.md       # AI agent usage instructions for tools
├── README.md                # Main documentation
├── ENHANCEMENTS.md          # v0.2.0 feature quick-reference
├── CLEANUP_SUMMARY.md       # Lint cleanup history
├── reactive_agent_architecture_integration_concept.md  # Design concept doc
└── .gitignore
```

## Source Package Layout (`src/mcp_logic/`)

The package uses **src-layout** (PEP 517), which prevents accidental imports from the project root.

### Module Dependency Graph

```
server.py
├── mace4_wrapper.py          (Mace4Wrapper)
├── hcc_prover.py             (check_contingency)
│   └── formula_ast.py        (parse, to_nnf, Formula types)
├── vfe_engine.py             (abductive_explain)
│   ├── formula_ast.py        (parse, complexity, ParseError)
│   └── hcc_prover.py         (check_contingency)
├── categorical_helpers.py    (CategoricalHelpers, group_axioms, monoid_axioms)
└── syntax_validator.py       (validate_formulas)
```

`formula_ast.py` is the **foundation** — it has no internal imports.
`hcc_prover.py` only imports from `formula_ast.py`.
`vfe_engine.py` imports from both `formula_ast.py` and `hcc_prover.py`.
`server.py` imports from all other modules.
`mace4_wrapper.py`, `categorical_helpers.py`, and `syntax_validator.py` have no internal imports.

## Key File Locations

| Purpose | File |
|---|---|
| MCP server entrypoint | `src/mcp_logic/server.py:cli()` |
| Tool definitions | `src/mcp_logic/server.py:handle_list_tools()` |
| Tool handlers | `src/mcp_logic/server.py:handle_call_tool()` |
| Prover9 logic | `src/mcp_logic/server.py:LogicEngine` |
| Mace4 logic | `src/mcp_logic/mace4_wrapper.py:Mace4Wrapper` |
| Propositional parser | `src/mcp_logic/formula_ast.py:parse()` |
| HCC checker | `src/mcp_logic/hcc_prover.py:check_contingency()` |
| VFE engine | `src/mcp_logic/vfe_engine.py:abductive_explain()` |
| Category theory | `src/mcp_logic/categorical_helpers.py:CategoricalHelpers` |
| Formula validation | `src/mcp_logic/syntax_validator.py:validate_formulas()` |
| Project config | `pyproject.toml` |
| Binary path config | CLI arg `--prover-path` (runtime) |

## Naming Conventions

- **Modules**: lowercase_underscores (`mace4_wrapper.py`, `hcc_prover.py`)
- **Classes**: PascalCase (`LogicEngine`, `Mace4Wrapper`, `SyntaxValidator`, `CategoricalHelpers`)
- **Dataclasses**: PascalCase frozen (`ProofStep`, `ContingencyResult`, `CandidateScore`, `AbductionResult`)
- **Functions**: lowercase_underscores (`check_contingency`, `validate_formulas`, `abductive_explain`)
- **Private methods**: leading underscore (`_create_input_file`, `_run_prover`, `_parse_model`)
- **Type aliases**: PascalCase (`Formula`, `Component`, `Hypersequent`)
- **Constants/Token types**: `_TOKEN_VAR`, `_COMPILED_PATTERNS` (module-level underscore prefix)

## Configuration Points

| What | Where |
|---|---|
| Prover9/Mace4 binary path | CLI arg `--prover-path` → `LogicEngine.__init__` |
| Mace4 domain size defaults | `mace4_wrapper.py` lines 62-64 (`domain_size=2`, `end_size=10`) |
| Subprocess timeout | Hardcoded 60s in `_run_prover()` and `_run_mace4()` |
| Logging level | `logging.basicConfig(level=logging.DEBUG)` in `server.py` (always DEBUG) |
| MCP server name | `Server("logic-manager")` in `main()` |
| pytest paths | `pyproject.toml [tool.pytest.ini_options]` |

# MCP-Logic

[![CI](https://github.com/angrysky56/mcp-logic/actions/workflows/ci.yml/badge.svg)](https://github.com/angrysky56/mcp-logic/actions/workflows/ci.yml)

An MCP server for automated first-order logic reasoning using Prover9 and Mace4.

## Features

- **Theorem Proving** - Prove logical statements with Prover9
- **Model Finding** - Find finite models with Mace4
- **Counterexample Finding** - Show why statements don't follow
- **Syntax Validation** - Pre-validate formulas with helpful error messages
- **Categorical Reasoning** - Built-in support for category theory proofs
- **Propositional Contingency** - Purely analytical HCC prover for fast propositional checks
- **Abductive Reasoning** - Rank hypotheses using Variational Free Energy (VFE)
- **Self-Contained** - All dependencies install automatically

## Quick Start

### Installation

**Linux/macOS:**

```bash
git clone https://github.com/angrysky56/mcp-logic
cd mcp-logic
./linux-setup-script.sh
```

**Windows:**

```cmd
git clone https://github.com/angrysky56/mcp-logic
cd mcp-logic
windows-setup-mcp-logic.bat
```

The setup script automatically:

- Downloads and builds LADR (Prover9 + Mace4)
- Creates Python virtual environment
- Installs all dependencies
- Generates Claude Desktop config

### Claude Desktop Integration

Add to your Claude Desktop MCP config (auto-generated at `claude-app-config.json`):

```json
{
  "mcpServers": {
    "mcp-logic": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/mcp-logic/src/mcp_logic",
        "run",
        "mcp_logic",
        "--prover-path",
        "/absolute/path/to/mcp-logic/ladr/bin"
      ]
    }
  }
}
```

**Important:** Replace `/absolute/path/to/mcp-logic` with your actual repository path.

## Available Tools

| Tool                     | Purpose                                                |
| ------------------------ | ------------------------------------------------------ |
| **prove**                | Prove statements using Prover9                         |
| **check-well-formed**    | Validate formula syntax with detailed errors           |
| **find_model**           | Find finite models satisfying premises                 |
| **find_counterexample**  | Find counterexamples showing statements don't follow   |
| **verify_commutativity** | Generate FOL for categorical diagram commutativity     |
| **get_category_axioms**  | Get axioms for category/functor/group/monoid           |
| **check_contingency**    | Check truth-functional contingency via HCC prover      |
| **abductive_explain**    | Find the VFE-minimizing explanation for an observation |

## Example Usage

### Prove a Theorem

```
Use the mcp-logic prove tool with:
premises: ["all x (man(x) -> mortal(x))", "man(socrates)"]
conclusion: "mortal(socrates)"
```

**Result:** ✓ THEOREM PROVED

### Analyze Propositional Contingency

```
Use the mcp-logic check_contingency tool with:
formula: "(p -> q) | (q -> p)"
```

**Result:** Identifies that the formula is a non-contingent **tautology**, returning the proof trace.

### Find a Counterexample

```
Use the mcp-logic find-counterexample tool with:
premises: ["P(a)"]
conclusion: "P(b)"
```

**Result:** Model found where `P(a)` is true but `P(b)` is false, proving the conclusion doesn't follow.

### Verify Categorical Diagram

```
Use the mcp-logic verify-commutativity tool with:
path_a: ["f", "g"]
path_b: ["h"]
object_start: "A"
object_end: "C"
```

**Result:** FOL premises and conclusion to prove that `f∘g = h`.

## Running Locally

**Instead of Claude Desktop, run the server directly:**

Linux/macOS:

```bash
./run_mcp_logic.sh
```

Windows:

```cmd
run_mcp_logic.bat
```

## Project Structure

```
mcp-logic/
├── src/mcp_logic/
│   ├── server.py              # Main MCP server (8 tools)
│   ├── mace4_wrapper.py       # Mace4 model finder
│   ├── syntax_validator.py    # Formula syntax validation
│   ├── categorical_helpers.py # Category theory utilities
│   ├── hcc_prover.py          # Hypersequent Contingency Calculus prover
│   ├── vfe_engine.py          # Variational Free Energy abductive engine
│   └── formula_ast.py         # Propositional logic AST and parser
├── ladr/                      # Auto-installed Prover9/Mace4 binaries
│   └── bin/
│       ├── prover9
│       └── mace4
├── tests/                     # Test suite
├── linux-setup-script.sh      # Linux/macOS setup
├── windows-setup-mcp-logic.bat # Windows setup
├── run_mcp_logic.sh           # Linux/macOS run script
└── run_mcp_logic.bat          # Windows run script
```

## What's New in v0.3.0

**Cognitive Architecture Enhancements:**

- ✅ **Hypersequent Contingency Calculus (HCC):** Added a rigorous deductive checker for evaluating propositional formula contingencies instantly without brute-force modeling.
- ✅ **Variational Free Energy (VFE) Engine:** Implemented abductive reasoning that ranks hypotheses using a non-dogmatic Cournot-Gaifman prior to elegantly satisfy Ockham's Razor.
- ✅ **Smart Prover Routing:** `prove` tool automatically routes pure propositional queries to the HCC engine, and first-order queries to Prover9.

## What's New in v0.2.0

**Enhanced Features:**

- ✅ Mace4 model finding and counterexample detection
- ✅ Detailed syntax validation with position-specific errors
- ✅ Categorical reasoning support (category theory axioms, commutativity verification)
- ✅ Structured JSON output from all tools
- ✅ Self-contained installation (no manual path configuration)

## Development

Run tests:

```bash
source .venv/bin/activate
pytest tests/ -v
```

Test components directly:

```bash
python tests/test_enhancements.py
```

## Documentation

- [`ENHANCEMENTS.md`](ENHANCEMENTS.md) - Quick reference for v0.2.0 features
- [`Documents/`](Documents/) - Detailed analysis and examples
- [`walkthrough.md`](.gemini/antigravity/brain/.../walkthrough.md) - Implementation details (in artifacts)

## Troubleshooting

**"Prover9 not found" error:**

- Run the setup script: `./linux-setup-script.sh` or `windows-setup-mcp-logic.bat`
- Check that `ladr/bin/prover9` and `ladr/bin/mace4` exist

**Server not updating:**

- Restart server after code changes
- Check logs for syntax errors

**Syntax validation warnings:**

- Use lowercase for predicates/functions (e.g., `man(x)` not `Man(x)`)
- Add spaces around operators for clarity
- Balance all parentheses

## License

MIT

## Credits

- **Prover9/Mace4**: William McCune's LADR library
- **LADR Repository**: [laitep/ladr](https://github.com/laitep/ladr)
- **Hypersequent Contingency Calculus (HCC)**: Based on the logical framework from "A Hypersequent Calculus for Classical Contingencies" by Eugenio Orlandelli, Giannandrea Pulcini, and Achille C. Varzi (2024).

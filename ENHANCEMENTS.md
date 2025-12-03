# MCP-Logic v0.2.0 - Enhanced with Mace4, Syntax Validation & Categorical Reasoning

## Quick Summary

**6 MCP Tools** total (2 existing + 4 new):

| Tool                   | Purpose                                       | Status                          |
| ---------------------- | --------------------------------------------- | ------------------------------- |
| `prove`                | Theorem proving with Prover9                  | ✓ Enhanced with validation      |
| `check-well-formed`    | Syntax validation                             | ✓ Enhanced with detailed errors |
| `find-model`           | Find finite models                            | ✅ NEW                          |
| `find-counterexample`  | Find counterexamples                          | ✅ NEW                          |
| `verify-commutativity` | Categorical diagram commutativity             | ✅ NEW                          |
| `get-category-axioms`  | Theory axioms (category/functor/group/monoid) | ✅ NEW                          |

## Installation (Self-Contained)

```bash
cd /home/ty/Repositories/mcp-logic
./linux-setup-script.sh
```

**That's it!** Automatically:

- Downloads & builds LADR (Prover9 + Mace4)
- Creates virtual environment
- Installs Python dependencies
- Generates `claude-app-config.json`

**No manual path configuration needed.**

## Usage

Add to Claude Desktop MCP config (auto-generated at `claude-app-config.json`):

```json
{
  "mcpServers": {
    "mcp-logic": {
      "command": "uv",
      "args": [
        "--directory",
        "/home/ty/Repositories/mcp-logic/src/mcp_logic",
        "run",
        "mcp_logic",
        "--prover-path",
        "/home/ty/Repositories/mcp-logic/ladr/bin"
      ]
    }
  }
}
```

**Remember:** Restart Claude Desktop after code changes.

## Example Usage

**Prove a theorem:**

```
use mcp-logic prove tool with:
premises: ["all x (man(x) -> mortal(x))", "man(socrates)"]
conclusion: "mortal(socrates)"
```

**Find counterexample:**

```
use mcp-logic find-counterexample tool with:
premises: ["P(a)"]
conclusion: "P(b)"
→ Shows model where P(a) is true but P(b) is false
```

**Verify categorical diagram:**

```
use mcp-logic verify-commutativity tool with:
path_a: ["f", "g"]
path_b: ["h"]
object_start: "A", object_end: "C"
→ Returns FOL premises to prove f∘g = h
```

## What's New

### Mace4 Model Finding

- Find finite models satisfying premises
- Find counterexamples proving statements DON'T follow
- Configurable domain sizes

### Syntax Validation

- Pre-validates formulas before Prover9
- Helpful error messages with positions
- Warnings for style improvements

### Categorical Reasoning

- Category theory axioms (identity, composition)
- Functor axioms (preservation properties)
- Natural transformation conditions
- Diagram commutativity verification

### Infrastructure

- Self-contained: all deps auto-installed
- Cross-platform binary detection
- Structured JSON output from all tools

## Files Changed

```
src/mcp_logic/
├── server.py              [MODIFIED] - Added 4 new tools, validation
├── mace4_wrapper.py       [NEW] - Mace4 model finder
├── syntax_validator.py    [NEW] - Formula syntax validation
└── categorical_helpers.py [NEW] - Category theory utilities
```

## Testing

```bash
cd /home/ty/Repositories/mcp-logic
source .venv/bin/activate
python tests/test_enhancements.py
```

Tests verify:

- ✓ Syntax validation with helpful errors
- ✓ Categorical axiom generation
- ✓ Commutativity diagram translation
- ✓ Existing Prover9 functionality unchanged

## Documentation

- [`walkthrough.md`](file:///home/ty/.gemini/antigravity/brain/d3c2bd10-3975-4c19-838e-25383611ec52/walkthrough.md) - Complete implementation details
- [`implementation_plan.md`](file:///home/ty/.gemini/antigravity/brain/d3c2bd10-3975-4c19-838e-25383611ec52/implementation_plan.md) - Original plan with dependency details
- [`task.md`](file:///home/ty/.gemini/antigravity/brain/d3c2bd10-3975-4c19-838e-25383611ec52/task.md) - Implementation checklist

## Version

**v0.2.0** - Enhanced with Mace4, syntax validation, and categorical reasoning

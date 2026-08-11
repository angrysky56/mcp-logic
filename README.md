# MCP-Logic

[![CI](https://github.com/angrysky56/mcp-logic/actions/workflows/ci.yml/badge.svg)](https://github.com/angrysky56/mcp-logic/actions/workflows/ci.yml)

An MCP server for automated first-order logic reasoning using Prover9, Mace4, and an onboard reasoning LLM.

## Features

- **Theorem Proving** - Prove logical statements with Prover9
- **Model Finding** - Find finite models with Mace4
- **Counterexample Finding** - Show why statements don't follow
- **Syntax Validation** - Pre-validate formulas with helpful error messages
- **Categorical Reasoning** - Built-in support for category theory proofs
- **Propositional Contingency** - Purely analytical HCC prover for fast propositional checks
- **Abductive Reasoning** - Rank hypotheses using Variational Free Energy (VFE)
- **🤖 Logic Advisor (NEW)** - Onboard [TwIL-LM3](https://huggingface.co/webAI-Official/TwIL-LM3) reasoning LLM that solves logic problems end-to-end: just ask a question in plain English
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

### Enable the Logic Advisor (Optional)

The onboard logic advisor uses a local 3B-parameter LLM ([TwIL-LM3 Q8](https://huggingface.co/webAI-Official/TwIL-LM3)) to solve logic problems end-to-end. Run the setup script to install it:

**Linux/macOS:**

```bash
./setup-advisor.sh
```

**Windows:**

```cmd
setup-advisor.bat
```

The script automatically:
- **Detects your GPU** — CUDA on NVIDIA (Linux/Windows), Metal on Apple Silicon (macOS), or falls back to CPU
- **Compiles `llama-cpp-python`** with the right acceleration backend
- **Downloads the model** (~3.3 GB, one-time) to `~/.cache/mcp-logic/models/`

> **No venv activation needed** — the setup scripts use `uv` which manages the virtual environment automatically. All `uv run` and `uv pip install --directory` commands target the project's `.venv` without you having to activate it first.

<details>
<summary><strong>Manual installation (advanced)</strong></summary>

If you prefer to install manually instead of using the setup script:

**Linux (NVIDIA GPU):**

```bash
CMAKE_ARGS="-DGGML_CUDA=on" uv pip install --directory . llama-cpp-python>=0.3.0
uv pip install --directory . huggingface-hub>=0.24.0
```

**macOS (Apple Silicon):**

```bash
CMAKE_ARGS="-DGGML_METAL=on" uv pip install --directory . llama-cpp-python>=0.3.0
uv pip install --directory . huggingface-hub>=0.24.0
```

**Windows (NVIDIA GPU, PowerShell):**

```powershell
$env:CMAKE_ARGS="-DGGML_CUDA=on"
uv pip install --directory . llama-cpp-python>=0.3.0
uv pip install --directory . huggingface-hub>=0.24.0
```

**CPU-only (any platform):**

```bash
uv pip install --directory . llama-cpp-python>=0.3.0
uv pip install --directory . huggingface-hub>=0.24.0
```

The model auto-downloads on first use, or pre-download manually:

```bash
uv run --directory . python -c "
from huggingface_hub import hf_hub_download
hf_hub_download('webAI-Official/TwIL-LM3', 'TwIL-LM3-Q8_0.gguf',
                local_dir='$HOME/.cache/mcp-logic/models',
                local_dir_use_symlinks=False)
"
```

</details>

### Platform Compatibility

| Platform | GPU Acceleration | Notes |
|----------|-----------------|-------|
| **Linux** (x86_64) | ✅ CUDA (NVIDIA) | Requires CUDA Toolkit + `nvidia-smi` |
| **macOS** (Apple Silicon) | ✅ Metal | Native ARM64 Python recommended |
| **macOS** (Intel) | ⚠️ Metal (limited) | Works but slower than Apple Silicon |
| **Windows** (x86_64) | ✅ CUDA (NVIDIA) | Requires CUDA Toolkit + Visual Studio Build Tools |
| **Any platform** | ✅ CPU | Always works, slower (~10-20s per query for 3B model) |

### Claude Desktop Integration

Add to your Claude Desktop MCP config (auto-generated at `claude-app-config.json`):

```json
{
  "mcpServers": {
    "mcp-logic": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/mcp-logic",
        "run",
        "python",
        "-m",
        "mcp_logic",
        "--prover-path",
        "/absolute/path/to/mcp-logic/ladr/bin"
      ]
    }
  }
}
```

**Important:** Replace `/absolute/path/to/mcp-logic` with your actual repository path.

To disable the advisor (e.g., on low-memory systems), add `"--no-advisor"` to the args list.

## Available Tools

| Tool                     | Purpose                                                |
| ------------------------ | ------------------------------------------------------ |
| **ask_logic_advisor** 🤖 | Solve logic problems in plain English (end-to-end)     |
| **prove**                | Prove statements using Prover9                         |
| **check_well_formed**    | Validate formula syntax with detailed errors           |
| **find_model**           | Find finite models satisfying premises                 |
| **find_counterexample**  | Find counterexamples showing statements don't follow   |
| **verify_commutativity** | Generate FOL for categorical diagram commutativity     |
| **get_category_axioms**  | Get axioms for category/functor/group/monoid           |
| **check_contingency**    | Check truth-functional contingency via HCC prover      |
| **abductive_explain**    | Find the VFE-minimizing explanation for an observation |

## Example Usage

### Ask the Logic Advisor (Easiest)

Just ask a question in natural language — the advisor formalizes it, runs the solver, and explains the result:

```
Use ask_logic_advisor with:
question: "Is it true that if all humans are mortal and Socrates is human,
           then Socrates is mortal?"
```

**Result:** The advisor translates to FOL, proves the theorem with Prover9, and returns:
> *"Yes, Socrates is mortal. The proof follows from the universal premise that all humans are mortal, combined with the fact that Socrates is human."*

The response also includes the formalization it used and the raw solver output for transparency.

### Prove a Theorem (Direct)

```
Use the prove tool with:
premises: ["all x (man(x) -> mortal(x))", "man(socrates)"]
conclusion: "mortal(socrates)"
```

**Result:** ✓ THEOREM PROVED

### Analyze Propositional Contingency

```
Use the check_contingency tool with:
formula: "(p -> q) | (q -> p)"
```

**Result:** Identifies that the formula is a non-contingent **tautology**, returning the proof trace.

### Find a Counterexample

```
Use the find_counterexample tool with:
premises: ["P(a)"]
conclusion: "P(b)"
```

**Result:** Model found where `P(a)` is true but `P(b)` is false, proving the conclusion doesn't follow.

### Verify Categorical Diagram

```
Use the verify_commutativity tool with:
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
│   ├── server.py              # Main MCP server (9 tools)
│   ├── logic_advisor.py       # Onboard TwIL-LM3 agentic solver
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
├── tests/                     # Test suite (171 tests)
├── linux-setup-script.sh      # Linux/macOS core setup
├── windows-setup-mcp-logic.bat # Windows core setup
├── setup-advisor.sh           # Linux/macOS advisor setup
├── setup-advisor.bat          # Windows advisor setup
├── run_mcp_logic.sh           # Linux/macOS run script
└── run_mcp_logic.bat          # Windows run script
```

## Logic Advisor Details

The `ask_logic_advisor` tool uses a 3-phase agentic pipeline:

```
  Natural Language Question
         │
         ▼
  ┌─────────────────────┐
  │ 1. FORMALIZE        │  TwIL-LM3 translates to FOL
  │    (LLM call)       │  → {"tool":"prove", "premises":[...], ...}
  └────────┬────────────┘
           ▼
  ┌─────────────────────┐
  │ 2. EXECUTE          │  Runs actual Prover9/Mace4/HCC
  │    (Solver call)    │  → {"result":"proved", "proof":...}
  └────────┬────────────┘
           ▼
  ┌─────────────────────┐
  │ 3. INTERPRET        │  TwIL-LM3 explains the result
  │    (LLM call)       │  → Plain English answer
  └─────────────────────┘
```

- **Model**: [TwIL-LM3](https://huggingface.co/webAI-Official/TwIL-LM3) (3B params, fine-tuned for formal reasoning)
- **Quantization**: Q8_0 GGUF (~3.3 GB on disk, ~3.5 GB VRAM)
- **Lazy loading**: Model loads on first query, not at server startup
- **License**: webAI Non-Commercial License v1.0 (non-commercial use only)

### Resource Requirements

| Scenario | VRAM | Inference Speed |
|----------|------|-----------------|
| NVIDIA GPU (CUDA) | ~3.5 GB | ~1-3s per LLM call |
| Apple Silicon (Metal) | ~3.5 GB | ~2-5s per LLM call |
| CPU-only | 0 (uses RAM) | ~10-20s per LLM call |

## What's New in v0.4.0

**Onboard Logic Advisor:**

- ✅ **ask_logic_advisor** tool: Solve logic problems in plain English — the onboard TwIL-LM3 LLM formalizes, runs the solver, and interprets results automatically
- ✅ **Cross-platform GPU setup**: Auto-detects CUDA (NVIDIA) or Metal (Apple Silicon) and compiles accordingly
- ✅ **Lazy model loading**: No VRAM used until the advisor is first called
- ✅ **Auto-download**: Model downloads from HuggingFace on first use

## What's New in v0.3.0

**Cognitive Architecture Enhancements:**

- ✅ **Hypersequent Contingency Calculus (HCC):** Added a rigorous deductive checker for evaluating propositional formula contingencies instantly without brute-force modeling.
- ✅ **Variational Free Energy (VFE) Engine:** Implemented abductive reasoning that ranks hypotheses using a non-dogmatic Cournot-Gaifman prior to elegantly satisfy Ockham's Razor.
- ✅ **Smart Prover Routing:** `prove` tool automatically routes pure propositional queries to the HCC engine, and first-order queries to Prover9.
- ✅ **Configurable Model Finder:** `find_model` and `find_counterexample` now support custom timeouts and structured predicate/function extraction.

## What's New in v0.2.0

**Enhanced Features:**

- ✅ Mace4 model finding and counterexample detection
- ✅ Detailed syntax validation with position-specific errors
- ✅ Categorical reasoning support (category theory axioms, commutativity verification)
- ✅ Structured JSON output from all tools
- ✅ Self-contained installation (no manual path configuration)

## Development

Run tests (no venv activation needed):

```bash
uv run --directory . pytest tests/ -v
```

## Documentation

- [`mcp_logic_agent.md`](mcp_logic_agent.md) - Agent guide (tool reference + workflows)
- [`ENHANCEMENTS.md`](ENHANCEMENTS.md) - Quick reference for v0.2.0 features
- [`Documents/`](Documents/) - Detailed analysis and examples

## Troubleshooting

**"Prover9 not found" error:**

- Run the setup script: `./linux-setup-script.sh` or `windows-setup-mcp-logic.bat`
- Check that `ladr/bin/prover9` and `ladr/bin/mace4` exist

**Logic advisor not working:**

- Run the advisor setup: `./setup-advisor.sh` or `setup-advisor.bat`
- Check GPU detection: `nvidia-smi` (Linux/Windows) or `system_profiler SPDisplaysDataType` (macOS)
- Force CPU mode: `./setup-advisor.sh --cpu`
- Check model exists: `ls ~/.cache/mcp-logic/models/TwIL-LM3-Q8_0.gguf`
- Disable if not needed: add `--no-advisor` to server args

**"llama-cpp-python" build fails:**

- **Linux**: Install build tools: `sudo apt-get install build-essential cmake`
- **macOS**: Install Xcode tools: `xcode-select --install`
- **Windows**: Install [Visual Studio Build Tools](https://visualstudio.microsoft.com/downloads/) with "Desktop development with C++" workload
- **CUDA**: Ensure CUDA Toolkit is installed and `nvcc` is in PATH

**Server not updating:**

- Restart server after code changes
- Check logs for syntax errors

**Syntax validation warnings:**

- Use lowercase for predicates/functions (e.g., `man(x)` not `Man(x)`)
- Add spaces around operators for clarity
- Balance all parentheses

## License

MIT (mcp-logic server)

> **Note:** The TwIL-LM3 model used by the logic advisor is licensed under the [webAI Non-Commercial License v1.0](https://huggingface.co/webAI-Official/TwIL-LM3). This restricts the advisor feature to non-commercial use. The core mcp-logic server (prove, find_model, etc.) remains MIT-licensed and usable commercially without the advisor.

## Credits

- **Prover9/Mace4**: William McCune's LADR library
- **LADR Repository**: [laitep/ladr](https://github.com/laitep/ladr)
- **TwIL-LM3**: [webAI](https://huggingface.co/webAI-Official/TwIL-LM3) — 3B reasoning model fine-tuned for formal logic
- **Hypersequent Contingency Calculus (HCC)**: Based on "A Hypersequent Calculus for Classical Contingencies" by Eugenio Orlandelli, Giannandrea Pulcini, and Achille C. Varzi (2024).

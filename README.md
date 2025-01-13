# MCP-Logic

An MCP server providing automated reasoning capabilities using Prover9/Mace4 for AI systems. This server enables logical theorem proving and logical model verification through a clean MCP interface.

## Design Philosophy

MCP-Logic bridges the gap between AI systems and formal logic by providing a robust interface to Prover9/Mace4. What makes it special:

- **AI-First Design**: Built specifically for AI systems to perform automated reasoning
- **Knowledge Validation**: Enables formal verification of knowledge representations and logical implications
- **Clean Integration**: Seamless integration with the Model Context Protocol (MCP) ecosystem
- **Deep Reasoning**: Support for complex logical proofs with nested quantifiers and multiple premises
- **Real-World Applications**: Particularly useful for validating AI knowledge models and reasoning chains

## Features

- Seamless integration with Prover9 for automated theorem proving
- Support for complex logical formulas and proofs
- Built-in syntax validation
- Clean MCP server interface
- Extensive error handling and logging
- Support for knowledge representation and reasoning about AI systems

## Quick Example

![image](https://github.com/user-attachments/assets/42756e3d-c2fa-475f-8e8a-25f7e444b2a4)

```python
# Prove that understanding + context leads to application
result = await prove(
    premises=[
        "all x all y (understands(x,y) -> can_explain(x,y))",
        "all x all y (can_explain(x,y) -> knows(x,y))",
        "all x all y (knows(x,y) -> believes(x,y))",
        "all x all y (believes(x,y) -> can_reason_about(x,y))",
        "all x all y (can_reason_about(x,y) & knows_context(x,y) -> can_apply(x,y))",
        "understands(system,domain)",
        "knows_context(system,domain)"
    ],
    conclusion="can_apply(system,domain)"
)
# Returns successful proof!
```

## Installation

### Prerequisites
- Python 3.12+
- UV package manager
- Prover9/Mace4 binaries (from https://www.cs.unm.edu/~mccune/prover9/gui/v05.html)

### Setup
1. Install Prover9/Mace4 to a known location (e.g., `F:/Prover9-Mace4/`)
2. Clone this repository
3. Install dependencies:
```bash
uv venv
uv pip install -e .
```

### Configuration
Add to your MCP environment configuration:
```json
{
  "mcpServers": {
    "mcp-logic": {
      "command": "uv",
      "args": [
        "--directory",
        "path/to/mcp-logic/src/mcp_logic",
        "run",
        "mcp_logic",
        "--prover-path",
        "path/to/Prover9-Mace4/bin-win32"
      ]
    }
  }
}
```

## Available Tools

### prove
Run logical proofs using Prover9:
```json
{
  "tool": "prove",
  "arguments": {
    "premises": [
      "all x (man(x) -> mortal(x))",
      "man(socrates)"
    ],
    "conclusion": "mortal(socrates)"
  }
}
```

### check-well-formed
Validate logical statement syntax:
```json
{
  "tool": "check-well-formed",
  "arguments": {
    "statements": [
      "all x (man(x) -> mortal(x))",
      "man(socrates)"
    ]
  }
}
```

## Documentation

See the [Documents](./Documents) folder for detailed analysis and examples:
- [Knowledge to Application](./Documents/KnowledgeToApplication.md): A formal logical analysis of understanding and practical application in AI systems

## Project Structure
```
mcp-logic/
├── src/
│   └── mcp_logic/
│       └── server.py    # Main MCP server implementation
├── tests/
│   ├── test_proofs.py   # Core functionality tests
│   └── test_debug.py    # Debug utilities
├── Documents/           # Analysis and documentation
├── pyproject.toml      # Python package config
└── README.md          # This file
```

## Development

Run tests:
```bash
uv pip install pytest
uv run pytest
```

## License

MIT

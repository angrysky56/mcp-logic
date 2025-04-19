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

![image](https://github.com/user-attachments/assets/61cecc1f-9ba1-4586-a6a2-83823088f763)

## Installation

### Prerequisites

- Python 3.10+
- UV package manager
- Git for cloning the repository
- CMake and build tools (for building LADR/Prover9)

### Setup

Clone this repository

```bash
git clone https://github.com/angrysky56/mcp-logic
cd mcp-logic
```

Run the setup script:
Windows run:

```bash
windows-setup-mcp-logic.bat
```

Linux/macOS:

```bash
chmod +x linux-setup-script.sh
./linux-setup-script.sh
```

The setup script:

- Checks for dependencies (git, cmake, build tools)
- Downloads LADR (Prover9/Mace4) from the external repository: [laitep/LADR](https://github.com/laitep/ladr.git)
- Builds the LADR library to create Prover9 binaries in the ladr/bin directory
- Creates a Python virtual environment
- Sets up configuration files for running with or without Docker

IMPORTANT: The LADR directory is not included in the repository itself and will be installed through the setup script or manually.

### Using Docker- no idea if this is working right, mainly designed for direct use with Claude Desktop

If you prefer to run with Docker this script:

- Finds an available port
- Activates the virtual environment
- Runs the server with the correct paths to the installed Prover9

```bash
# Linux/macOS
./run-mcp-logic.sh

# Windows
run-mcp-logic.bat
```

These scripts will build and run a Docker container with the necessary environment.

### Claude Desktop Integration

To use MCP-Logic with Claude Desktop, use this configuration:

```json
{
  "mcpServers": {
    "mcp-logic": {
      "command": "uv",
      "args": [
        "--directory", 
        "/path/to/mcp-logic/src/mcp_logic",
        "run", 
        "mcp_logic", 
        "--prover-path", 
        "/path/to/mcp-logic/ladr/bin"
      ]
    }
  }
}
```

Replace "/path/to/mcp-logic" with your actual repository path.

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

```markdown
mcp-logic/
├── src/
│   └── mcp_logic/
│       └── server.py   # Main MCP server implementation
├── tests/
│   ├── test_proofs.py  # Core functionality tests
│   └── test_debug.py   # Debug utilities
├── Documents/          # Analysis and documentation
├── pyproject.toml      # Python package config
├── setup-script.sh     # Setup script (installs LADR & dependencies)
├── run-mcp-logic.sh    # Docker-based run script (Linux/macOS)
├── run-mcp-logic.bat   # Docker-based run script (Windows)
├── run-mcp-logic-local.sh # Local run script (no Docker)
└── README.md           # This file
```

Note: After running setup-script.sh, a "ladr" directory will be created containing the Prover9 binaries, but this directory is not included in the repository itself.

## Development

Run tests:

```bash
uv pip install pytest
uv run pytest
```

## License

MIT

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

{'result': 'proved', 'proof': '', 'complete_output': '============================== Prover9 ===============================\nProver9 (32) version Dec-2007, Dec 2007.\nProcess 27928 was started by angry on Ty,\nMon Jan 13 16:10:57 2025\nThe command was "/cygdrive/f/Prover9-Mace4/bin-win32/prover9 -f C:\\Users\\angry\\AppData\\Local\\Temp\\tmp05_k_2ak.in".\n============================== end of head ===========================\n\n============================== INPUT =================================\n\n% Reading from file C:\\Users\\angry\\AppData\\Local\\Temp\\tmp05_k_2ak.in\n\n\nformulas(assumptions).\n(all x all y (understands(x,y) -> can_explain(x,y))).\n(all x all y (can_explain(x,y) -> knows(x,y))).\n(all x all y (knows(x,y) -> believes(x,y))).\n(all x all y (believes(x,y) -> can_reason_about(x,y))).\n(all x all y (can_reason_about(x,y) & knows_context(x,y) -> can_apply(x,y))).\nunderstands(system,domain).\nknows_context(system,domain).\nend_of_list.\n\nformulas(goals).\ncan_apply(system,domain).\nend_of_list.\n\n============================== end of input ==========================\n\n============================== PROCESS NON-CLAUSAL FORMULAS ==========\n\n% Formulas that are not ordinary clauses:\n1 (all x all y (understands(x,y) -> can_explain(x,y))) # label(non_clause).  [assumption].\n2 (all x all y (can_explain(x,y) -> knows(x,y))) # label(non_clause).  [assumption].\n3 (all x all y (knows(x,y) -> believes(x,y))) # label(non_clause).  [assumption].\n4 (all x all y (believes(x,y) -> can_reason_about(x,y))) # label(non_clause).  [assumption].\n5 (all x all y (can_reason_about(x,y) & knows_context(x,y) -> can_apply(x,y))) # label(non_clause).  [assumption].\n6 can_apply(system,domain) # label(non_clause) # label(goal).  [goal].\n\n============================== end of process non-clausal formulas ===\n\n============================== PROCESS INITIAL CLAUSES ===============\n\n% Clauses before input processing:\n\nformulas(usable).\nend_of_list.\n\nformulas(sos).\n-understands(x,y) | can_explain(x,y).  [clausify(1)].\n-can_explain(x,y) | knows(x,y).  [clausify(2)].\n-knows(x,y) | believes(x,y).  [clausify(3)].\n-believes(x,y) | can_reason_about(x,y).  [clausify(4)].\n-can_reason_about(x,y) | -knows_context(x,y) | can_apply(x,y).  [clausify(5)].\nunderstands(system,domain).  [assumption].\nknows_context(system,domain).  [assumption].\n-can_apply(system,domain).  [deny(6)].\nend_of_list.\n\nformulas(demodulators).\nend_of_list.\n\n============================== PREDICATE ELIMINATION =================\n\nEliminating understands/2\n7 understands(system,domain).  [assumption].\n8 -understands(x,y) | can_explain(x,y).  [clausify(1)].\nDerived: can_explain(system,domain).  [resolve(7,a,8,a)].\n\nEliminating can_explain/2\n9 can_explain(system,domain).  [resolve(7,a,8,a)].\n10 -can_explain(x,y) | knows(x,y).  [clausify(2)].\nDerived: knows(system,domain).  [resolve(9,a,10,a)].\n\nEliminating knows/2\n11 knows(system,domain).  [resolve(9,a,10,a)].\n12 -knows(x,y) | believes(x,y).  [clausify(3)].\nDerived: believes(system,domain).  [resolve(11,a,12,a)].\n\nEliminating believes/2\n13 believes(system,domain).  [resolve(11,a,12,a)].\n14 -believes(x,y) | can_reason_about(x,y).  [clausify(4)].\nDerived: can_reason_about(system,domain).  [resolve(13,a,14,a)].\n\nEliminating can_reason_about/2\n15 can_reason_about(system,domain).  [resolve(13,a,14,a)].\n16 -can_reason_about(x,y) | -knows_context(x,y) | can_apply(x,y).  [clausify(5)].\nDerived: -knows_context(system,domain) | can_apply(system,domain).  [resolve(15,a,16,a)].\n\nEliminating knows_context/2\n17 -knows_context(system,domain) | can_apply(system,domain).  [resolve(15,a,16,a)].\n18 knows_context(system,domain).  [assumption].\nDerived: can_apply(system,domain).  [resolve(17,a,18,a)].\n\nEliminating can_apply/2\n19 can_apply(system,domain).  [resolve(17,a,18,a)].\n20 -can_apply(system,domain).  [deny(6)].\nDerived: $F.  [resolve(19,a,20,a)].\n\n============================== end predicate elimination =============\n\nAuto_denials:  (no changes).\n\nTerm ordering decisions:\nPredicate symbol precedence:  predicate_order([ ]).\nFunction symbol precedence:  function_order([ ]).\nAfter inverse_order:  (no changes).\nUnfolding symbols: (none).\n\nAuto_inference settings:\n  % set(neg_binary_resolution).  % (HNE depth_diff=0)\n  % clear(ordered_res).  % (HNE depth_diff=0)\n  % set(ur_resolution).  % (HNE depth_diff=0)\n    % set(ur_resolution) -> set(pos_ur_resolution).\n    % set(ur_resolution) -> set(neg_ur_resolution).\n\nAuto_process settings:  (no changes).\n\n============================== PROOF =================================\n\n% Proof 1 at 0.00 (+ 0.00) seconds.\n% Length of proof is 21.\n% Level of proof is 8.\n% Maximum clause weight is 0.\n% Given clauses 0.\n\n1 (all x all y (understands(x,y) -> can_explain(x,y))) # label(non_clause).  [assumption].\n2 (all x all y (can_explain(x,y) -> knows(x,y))) # label(non_clause).  [assumption].\n3 (all x all y (knows(x,y) -> believes(x,y))) # label(non_clause).  [assumption].\n4 (all x all y (believes(x,y) -> can_reason_about(x,y))) # label(non_clause).  [assumption].\n5 (all x all y (can_reason_about(x,y) & knows_context(x,y) -> can_apply(x,y))) # label(non_clause).  [assumption].\n6 can_apply(system,domain) # label(non_clause) # label(goal).  [goal].\n7 understands(system,domain).  [assumption].\n8 -understands(x,y) | can_explain(x,y).  [clausify(1)].\n9 can_explain(system,domain).  [resolve(7,a,8,a)].\n10 -can_explain(x,y) | knows(x,y).  [clausify(2)].\n11 knows(system,domain).  [resolve(9,a,10,a)].\n12 -knows(x,y) | believes(x,y).  [clausify(3)].\n13 believes(system,domain).  [resolve(11,a,12,a)].\n14 -believes(x,y) | can_reason_about(x,y).  [clausify(4)].\n15 can_reason_about(system,domain).  [resolve(13,a,14,a)].\n16 -can_reason_about(x,y) | -knows_context(x,y) | can_apply(x,y).  [clausify(5)].\n17 -knows_context(system,domain) | can_apply(system,domain).  [resolve(15,a,16,a)].\n18 knows_context(system,domain).  [assumption].\n19 can_apply(system,domain).  [resolve(17,a,18,a)].\n20 -can_apply(system,domain).  [deny(6)].\n21 $F.  [resolve(19,a,20,a)].\n\n============================== end of proof ==========================\n\n============================== STATISTICS ============================\n\nGiven=0. Generated=1. Kept=0. proofs=1.\nUsable=0. Sos=0. Demods=0. Limbo=0, Disabled=15. Hints=0.\nWeight_deleted=0. Literals_deleted=0.\nForward_subsumed=0. Back_subsumed=0.\nSos_limit_deleted=0. Sos_displaced=0. Sos_removed=0.\nNew_demodulators=0 (0 lex), Back_demodulated=0. Back_unit_deleted=0.\nDemod_attempts=0. Demod_rewrites=0.\nRes_instance_prunes=0. Para_instance_prunes=0. Basic_paramod_prunes=0.\nNonunit_fsub_feature_tests=0. Nonunit_bsub_feature_tests=0.\nMegabytes=0.02.\nUser_CPU=0.00, System_CPU=0.00, Wall_clock=0.\n\n============================== end of statistics =====================\n\n============================== end of search =========================\n\nTHEOREM PROVED\n\nExiting with 1 proof.\n\nProcess 27928 exit (max_proofs) Mon Jan 13 16:10:57 2025\n'}

![image](https://github.com/user-attachments/assets/61cecc1f-9ba1-4586-a6a2-83823088f763)

## Installation

### Prerequisites

- Python 3.12+
- UV package manager
- Prover9/Mace4 binaries (from <https://www.cs.unm.edu/~mccune/prover9/gui/v05.html>)

### Setup

1. Install Prover9/Mace4 to a known location (e.g., `F:/Prover9-Mace4/`)
2. Clone this repository
3. Install dependencies:


uv venv
uv pip install -e .


### Configuration

Add to your MCP environment configuration:


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

## Development

Run tests:

```bash
uv pip install pytest
uv run pytest
```

## License

MIT

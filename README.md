# MCP-Logic

An MCP server providing automated reasoning capabilities using Prover9/Mace4 for AI systems. This server enables logical theorem proving and model finding through a clean MCP interface.

## About

MCP-Logic bridges the gap between AI systems and formal logic by providing a robust interface to Prover9/Mace4. What makes it special:

- **AI-First Design**: Built specifically for AI systems to perform automated reasoning
- **Knowledge Validation**: Enables formal verification of knowledge representations and logical implications
- **Clean Integration**: Seamless integration with the Model Context Protocol (MCP) ecosystem
- **Deep Reasoning**: Support for complex logical proofs with nested quantifiers and multiple premises
- **Real-World Applications**: Particularly useful for validating AI knowledge models and reasoning chains

## Quick Example: Validating AI Understanding

This example demonstrates how MCP-Logic can formally verify the relationship between understanding and practical application:

```python
# Prove that understanding combined with context enables practical application
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

# Returns a successful proof that if a system truly understands a domain
# and knows its context, it can apply that knowledge practically.
```

## Interactive Demo

Try these proofs to explore the system's capabilities:

1. **Basic Syllogism**:
```python
result = await prove(
    premises=[
        "all x (mortal(x) -> will_end(x))",
        "all x (human(x) -> mortal(x))",
        "human(socrates)"
    ],
    conclusion="will_end(socrates)"
)
```

2. **Transitive Knowledge**:
```python
result = await prove(
    premises=[
        "all x all y (teaches(x,y) -> knows(x,y))",
        "all x all y (studies_under(x,y) -> learns_from(x,y))",
        "all x all y (learns_from(x,y) & knows(y,z) -> gains_knowledge(x,z))",
        "teaches(aristotle,logic)",
        "studies_under(alexander,aristotle)"
    ],
    conclusion="gains_knowledge(alexander,logic)"
)
```

3. **Complex Relationships**:
```python
result = await prove(
    premises=[
        "all x all y (influences(x,y) -> shapes_thinking(x,y))",
        "all x all y (shapes_thinking(x,y) -> leaves_legacy(x,y))",
        "all x all y all z (leaves_legacy(x,y) & follows_teachings(z,y) -> influenced_by(z,x))",
        "influences(plato,aristotle)",
        "follows_teachings(alexander,aristotle)"
    ],
    conclusion="influenced_by(alexander,plato)"
)
```

[... rest of the README content ...]

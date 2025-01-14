# CodebaseDetails

## Purpose and Overview

The MCP Logic codebase implements a bridge between the Model Context Protocol (MCP) and the Prover9/Mace4 automated theorem proving system. Key components include:

1. MCP Server Implementation:
   - Request handling
   - Result formatting
   - Error management
   - Integration interfaces

2. Prover9/Mace4 Integration:
   - Input formatting
   - Output parsing
   - Process management
   - Resource control

3. Logic System Support:
   - First-order logic
   - Modal logic
   - Multi-agent reasoning
   - Temporal logic

4. Knowledge Management:
   - Theorem storage
   - Proof caching
   - Result persistence
   - Integration APIs
[Why this domain is critical to the project]

## Step-by-Step Explanations

### Core Components Implementation

1. Server Setup:
```python
class LogicServer(Server):
    def __init__(self, prover_path: str):
        super().__init__("mcp-logic")
        self.prover = Prover9(prover_path)
        self.mace4 = Mace4(prover_path)
```

2. Request Handler:
```python
@server.call_tool()
async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[types.Content]:
    if name == "prove":
        return await handle_prove(arguments)
    elif name == "check-well-formed":
        return await handle_check_well_formed(arguments)
```

3. Proof Processing:
```python
async def handle_prove(args: dict) -> list[types.Content]:
    premises = args["premises"]
    conclusion = args["conclusion"]
    
    # Format for Prover9
    input_str = format_proof_input(premises, conclusion)
    
    # Run proof search
    result = await self.prover.prove(input_str)
    
    if not result.success:
        # Try counterexample
        model = await self.mace4.find_model(input_str)
        return format_counterexample(model)
        
    return format_proof(result)
```

### Integration Implementation

1. Neo4j Connection:
```python
async def store_theorem(proof_result: ProofResult) -> None:
    query = """
    CREATE (t:Theorem {
        premises: $premises,
        conclusion: $conclusion,
        proof: $proof
    })
    """
    await neo4j.execute_query(query, {
        "premises": proof_result.premises,
        "conclusion": proof_result.conclusion,
        "proof": proof_result.steps
    })
```

2. Resource Management:
```python
class ProverProcess:
    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.process = None
    
    async def run(self, input_str: str) -> str:
        self.process = await asyncio.create_subprocess_exec(
            self.prover_path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE
        )
        try:
            stdout, _ = await asyncio.wait_for(
                self.process.communicate(input_str.encode()),
                timeout=self.timeout
            )
            return stdout.decode()
        except asyncio.TimeoutError:
            self.process.terminate()
            raise TimeoutError("Proof search exceeded timeout")
```

### Error Handling Implementation

1. Syntax Validation:
```python
def validate_formula(formula: str) -> bool:
    try:
        tokens = tokenize(formula)
        parse_tree = parse(tokens)
        return True
    except SyntaxError as e:
        return False
```

2. Error Response:
```python
def format_error(error: Exception) -> list[types.Content]:
    return [types.TextContent(
        type="text",
        text=f"Error: {str(error)}"
    )]
```
[Concrete, detailed steps for implementation and maintenance]

## Annotated Examples

### 1. Complete Proof Example

```python
# Example of a complete proof implementation
from mcp_logic.server import LogicServer
from mcp_logic.prover import ProofResult
from mcp_logic.formatter import format_proof_input

async def prove_with_explanation(
    premises: list[str],
    conclusion: str,
    server: LogicServer
) -> ProofResult:
    # Format the input
    input_str = format_proof_input(
        premises=premises,
        conclusion=conclusion,
        # Add formatting options
        options={
            "max_seconds": 30,
            "max_weight": 100,
            "max_proofs": 1
        }
    )
    
    # Attempt proof
    try:
        result = await server.prover.prove(input_str)
        if result.success:
            # Store successful proof
            await store_theorem(result)
            return result
        else:
            # Try for counterexample
            model = await server.mace4.find_model(input_str)
            return ProofResult(
                success=False,
                counterexample=model
            )
    except Exception as e:
        logger.error(f"Proof error: {e}")
        raise
```

### 2. Modal Logic Implementation

```python
# Modal logic handling example
def format_modal_proof(
    premises: list[str],
    conclusion: str
) -> str:
    # Define modal operators
    preamble = """
    formulas(assumptions).
        # Modal logic operators
        all x (box(x) -> -dia(-x)).
        all x y (box(x & y) <-> box(x) & box(y)).
    end_of_list.
    """
    
    # Format premises with modal operators
    formatted_premises = [
        format_modal_formula(p)
        for p in premises
    ]
    
    return f"{preamble}\n" + "\n".join(formatted_premises)
```

### 3. Integration Example

```python
# Neo4j integration for theorem storage
class TheoremStore:
    def __init__(self, neo4j_uri: str):
        self.driver = GraphDatabase.driver(neo4j_uri)
    
    async def store_proof(
        self,
        proof: ProofResult
    ) -> None:
        # Create theorem node
        await self.driver.execute_query("""
        CREATE (t:Theorem {
            premises: $premises,
            conclusion: $conclusion
        })
        WITH t
        UNWIND $steps as step
        CREATE (s:ProofStep {
            description: step.description,
            formula: step.formula
        })
        CREATE (t)-[:HAS_STEP]->(s)
        """, {
            "premises": proof.premises,
            "conclusion": proof.conclusion,
            "steps": proof.steps
        })
```
[Code snippets, diagrams, or flowcharts for clarity]

## Contextual Notes

### Architecture Decisions

1. Async Implementation:
   - Used asyncio for process management
   - Prevents blocking on long proofs
   - Enables concurrent proof attempts
   - Facilitates integration with MCP

2. Process Management:
   - Separate processes for Prover9 and Mace4
   - Timeout controls
   - Resource monitoring
   - Clean process termination

3. Storage Strategy:
   - Neo4j for theorem storage
   - Graph representation of proofs
   - Caching of common patterns
   - Result persistence

### Development History

1. Initial Version:
   - Basic Prover9 integration
   - Simple proof formatting
   - Limited error handling
   - Direct process calls

2. Current Version:
   - Full async support
   - Robust error handling
   - Modal logic support
   - Neo4j integration

3. Future Plans:
   - Enhanced modal operators
   - Temporal logic support
   - Distributed proving
   - Proof visualization

### Technical Constraints

1. Performance:
   - Proof search can be exponential
   - Memory usage can grow rapidly
   - Process overhead for each proof
   - Network latency for storage

2. Compatibility:
   - Prover9 syntax requirements
   - MCP protocol constraints
   - Neo4j version dependencies
   - Python async limitations

3. Scalability:
   - Process pool management
   - Database connection limits
   - Memory constraints
   - Network bandwidth
[Historical decisions, trade-offs, and anticipated challenges]

## Actionable Advice

### Development Guidelines

1. Code Organization:
```python
# Maintain clear module separation
from mcp_logic import (
    server,      # MCP server implementation
    prover,      # Prover9/Mace4 interface
    formatter,   # Input/output formatting
    storage,     # Theorem storage
    types        # Type definitions
)

# Use type hints consistently
async def prove(
    premises: list[str],
    conclusion: str,
    timeout: Optional[int] = None
) -> ProofResult:
    pass

# Document complex functions
def format_modal_formula(formula: str) -> str:
    """
    Format a modal logic formula for Prover9.
    
    Args:
        formula: Raw modal logic formula
        
    Returns:
        Formatted Prover9 input string
        
    Raises:
        SyntaxError: If formula is malformed
    """
    pass
```

2. Error Handling:
```python
# Use custom exceptions
class ProverError(Exception):
    pass

class SyntaxError(ProverError):
    pass

class TimeoutError(ProverError):
    pass

# Implement proper error handling
try:
    result = await prover.prove(input_str)
except SyntaxError as e:
    logger.error(f"Invalid formula: {e}")
    raise
except TimeoutError:
    logger.warning("Proof search timed out")
    return ProofResult(success=False, reason="timeout")
except Exception as e:
    logger.error(f"Unexpected error: {e}")
    raise
```

3. Testing Strategy:
```python
# Unit tests for core functionality
def test_modal_formula_formatting():
    assert format_modal_formula("box(P)") == "box(P)"
    with pytest.raises(SyntaxError):
        format_modal_formula("box(")

# Integration tests
async def test_proof_workflow():
    server = LogicServer()
    result = await server.prove(
        premises=["P -> Q", "P"],
        conclusion="Q"
    )
    assert result.success
    assert len(result.steps) > 0
```

### Performance Optimization

1. Process Management:
```python
# Use process pools for concurrent proofs
class ProverPool:
    def __init__(self, max_workers: int = 4):
        self.semaphore = asyncio.Semaphore(max_workers)
        self.workers = []
    
    async def prove(self, input_str: str) -> ProofResult:
        async with self.semaphore:
            worker = ProverProcess()
            self.workers.append(worker)
            try:
                return await worker.prove(input_str)
            finally:
                self.workers.remove(worker)
```

2. Memory Management:
```python
# Implement clean resource handling
class ProverProcess:
    async def __aenter__(self):
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc, tb):
        await self.cleanup()
    
    async def cleanup(self):
        if self.process:
            try:
                self.process.terminate()
                await self.process.wait()
            except Exception:
                self.process.kill()
```

### Maintenance Tasks

1. Regular Checks:
```python
# Health check implementation
async def check_system_health() -> bool:
    try:
        # Test prover availability
        await self.prover.test_connection()
        
        # Check database connection
        await self.storage.ping()
        
        # Verify process pool
        assert len(self.pool.workers) <= self.pool.max_workers
        
        return True
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return False
```

2. Monitoring:
```python
# Performance metrics
class ProverMetrics:
    def __init__(self):
        self.proof_times = []
        self.success_rate = 0.0
        self.memory_usage = []
    
    def record_proof_attempt(
        self,
        success: bool,
        duration: float,
        memory_mb: float
    ):
        self.proof_times.append(duration)
        self.memory_usage.append(memory_mb)
        total = len(self.proof_times)
        successes = sum(1 for t in self.proof_times if t > 0)
        self.success_rate = successes / total

# Regular monitoring
async def monitor_system():
    while True:
        metrics = await collect_metrics()
        if metrics.success_rate < 0.8:
            logger.warning("Success rate below threshold")
        if max(metrics.memory_usage) > 1000:
            logger.warning("High memory usage detected")
        await asyncio.sleep(300)
```
[Gotchas, edge cases, and common pitfalls to avoid]

"""Logic Advisor — agentic solver powered by a local reasoning LLM.

Provides a single-shot ``solve`` interface: the client poses a logic
question in natural language, and the advisor **formalizes** it into
Prover9/Mace4 syntax, **runs** the actual solver, and **interprets**
the result — all in one call.

Architecture (3-phase pipeline)::

    ┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
    │ 1. Formalize │────▶│ 2. Execute   │────▶│ 3. Interpret    │
    │ (LLM call)   │     │ (Solver call) │     │ (LLM call)      │
    └─────────────┘     └──────────────┘     └─────────────────┘
    NL → structured      Run prove /          Solver output →
    plan (JSON)          find_model / etc.     plain-English answer

The model is **lazy-loaded** on first query to avoid startup latency
and VRAM waste when clients don't need the advisor.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from mcp_logic.epistemic_status import EpistemicStatus, with_status
from mcp_logic.fol_ast import ParseError
from mcp_logic.fol_ast import parse as parse_fol
from mcp_logic.syntax_contract import PROVER9_SYNTAX_RULES

if TYPE_CHECKING:
    pass

logger = logging.getLogger("mcp_logic.logic_advisor")

# ── Constants ───────────────────────────────────────────────────────────
_HF_REPO_ID = "webAI-Official/TwIL-LM3"
# Immutable repository commit used for reproducible, supply-chain-safe model
# downloads. Update deliberately after reviewing upstream model changes.
_HF_REVISION = "5d90f3a3251e142fc5cc6b42a62b175fdb0d4ccd"
_GGUF_FILENAME = "TwIL-LM3-Q8_0.gguf"
_DEFAULT_CACHE_DIR = Path.home() / ".cache" / "mcp-logic" / "models"

# Strip <think>…</think> reasoning blocks from output.
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
# An opening <think> with no matching close — the model never left reasoning
# mode. The tag must still go, but the text after it is kept: the answer is
# often in there.
_OPEN_THINK_RE = re.compile(r"<think>", re.IGNORECASE)

# ── Decoding settings (from the TwIL-LM3 model card) ────────────────────
# The card is explicit on all three, and each was wrong in the first cut:
#   * greedy decoding — "Pass --temp 0, because the evaluation is greedy
#     while the packaged sampling defaults are not."
#   * >= 2048 generation budget — the model opens a <think> block before
#     answering and "a short budget truncates it, which costs far more
#     accuracy than the quantization does."
#   * repetition_penalty 1.0 — "load-bearing"; llama.cpp defaults to 1.1.
_DEFAULT_TEMPERATURE = 0.0
_DEFAULT_MAX_TOKENS = 2048
_REPEAT_PENALTY = 1.0
# Eval protocol uses max_seq_len 8192; 4096 leaves no room for prompt +
# reasoning + answer at a 2048-token budget.
_DEFAULT_N_CTX = 8192

#: Answers are deterministic (greedy decoding), so a repeat question can be
#: served from memory instead of re-running the GPU.
_DEFAULT_CACHE_SIZE = 128

#: Drop the model out of VRAM after this long without a query. ~3.3 GB is a
#: lot to hold for a tool that may be used a few times an hour, and idle
#: VRAM still costs heat.  ``None`` keeps it resident forever.
_DEFAULT_IDLE_UNLOAD_SECONDS = 600.0

# Keys in a plan whose values are formula text needing normalization.
_FORMULA_LIST_KEYS = ("premises", "statements")
_FORMULA_STR_KEYS = ("conclusion", "formula")

# Small models reliably drift into Unicode logic notation or Prolog/C-style
# operators despite prompt instructions.  Rewriting is cheaper and far more
# reliable than re-prompting, and non-UTF-8 bytes reaching Prover9 used to
# crash the subprocess decode.  Order matters: multi-char before single-char.
_SYNTAX_REWRITES: tuple[tuple[str, str], ...] = (
    # Unicode quantifiers and connectives.
    ("∀", "all "),  # ∀
    ("∃", "exists "),  # ∃
    ("↔", "<->"),  # ↔
    ("⇔", "<->"),  # ⇔
    ("→", "->"),  # →
    ("⇒", "->"),  # ⇒
    ("∧", "&"),  # ∧
    ("∨", "|"),  # ∨
    ("¬", "-"),  # ¬
    ("≠", "!="),  # ≠
    ("⊥", "$F"),  # ⊥
    ("⊤", "$T"),  # ⊤
    # ASCII variants from other proof-assistant dialects.
    ("<=>", "<->"),
    ("=>", "->"),
    ("||", "|"),
    ("&&", "&"),
    ("~", "-"),
    ("forall ", "all "),
    ("exist ", "exists "),
)

# Collapse the double spaces introduced by quantifier rewrites.
_MULTISPACE_RE = re.compile(r"[ \t]{2,}")


class FormulaTheory(str, Enum):
    """Theory features found in a parsed formalization."""

    PURE_FOL = "pure_fol"
    ARITHMETIC = "arithmetic"
    MIXED = "mixed"
    MALFORMED = "malformed"


_SMT_ARITHMETIC_HEADS = frozenset(
    {"+", "-", "*", "/", "div", "mod", "rem", "abs", ">", "<", ">=", "<="}
)
_SMT_LOGIC_HEADS = frozenset(
    {"and", "or", "not", "xor", "=>", "=", "distinct", "ite", "let"}
)
_SMT_TOKEN_RE = re.compile(r"\s*([()]|[^()\s]+)")
_SMT_NUMERAL_RE = re.compile(r"-?(?:\d+(?:\.\d*)?|\.\d+)\Z")


def _parse_s_expression(source: str) -> object:
    """Parse one SMT-LIB S-expression into nested Python lists."""

    tokens = [match.group(1) for match in _SMT_TOKEN_RE.finditer(source)]
    index = 0

    def parse_item() -> object:
        nonlocal index
        if index >= len(tokens):
            raise ValueError("unexpected end of SMT-LIB expression")
        lexeme = tokens[index]
        index += 1
        if lexeme != "(":
            if lexeme == ")":
                raise ValueError("unexpected closing parenthesis")
            return lexeme
        items: list[object] = []
        while index < len(tokens) and tokens[index] != ")":
            items.append(parse_item())
        if index >= len(tokens):
            raise ValueError("unclosed SMT-LIB expression")
        index += 1
        return items

    parsed = parse_item()
    if index != len(tokens):
        raise ValueError("multiple SMT-LIB expressions on one formula line")
    return parsed


def _smt_theory_features(expression: object) -> tuple[bool, bool]:
    """Return ``(has_arithmetic, has_uninterpreted_application)``."""

    if isinstance(expression, str):
        return bool(_SMT_NUMERAL_RE.fullmatch(expression)), False
    if not isinstance(expression, list) or not expression:
        return False, False
    head = expression[0]
    if not isinstance(head, str):
        return False, False

    arithmetic = head in _SMT_ARITHMETIC_HEADS
    uninterpreted = head not in (
        _SMT_ARITHMETIC_HEADS | _SMT_LOGIC_HEADS | {"forall", "exists"}
    )
    children = expression[2:] if head in {"forall", "exists"} else expression[1:]
    for child in children:
        child_arithmetic, child_uninterpreted = _smt_theory_features(child)
        arithmetic = arithmetic or child_arithmetic
        uninterpreted = uninterpreted or child_uninterpreted
    return arithmetic, uninterpreted


# Arithmetic written in Prover9 syntax: comparison/arithmetic operators, or a
# bare numeral used as a term. Prover9 has no theory for any of it, so a
# translation containing these needs re-translating into SMT-LIB.
# Logical connectives are stripped BEFORE looking for arithmetic: `->` and
# `<->` contain `>` and `<`, and `=` is ordinary FOL equality, not arithmetic.
_FOL_CONNECTIVE_RE = re.compile(r"<->|<=>|->|!=|=|&|\|")
# Symbols and numerals only. Word-shaped names like `lt`, `gt` or `div` are
# deliberately NOT listed: `all x all y (lt(x,y) -> -lt(y,x))` is a strict
# order relation in pure first-order logic, and treating it as arithmetic
# would misroute the dense-order theory that this project keeps as its
# standard "consistent but no finite model" control.
_ARITHMETIC_IN_FOL_RE = re.compile(r"[<>+*/]|\b\d+\b")
#: Stricter: an actual arithmetic operator, no bare numerals. Used when
#: probing an unlabelled reply, where a stray digit (a JSON ``domain_size``,
#: say) is not evidence of arithmetic.
_ARITHMETIC_OPERATOR_RE = re.compile(r"[<>+*/]")


def needs_smt_retranslation(
    formulas: list[str], *, operators_only: bool = False
) -> bool:
    """Whether a Prover9 translation reaches for arithmetic it cannot express.

    The model is asked for Prover9 first because a single narrow translation
    task is what it does well — measured 9/9 solver-accepted, against 3/9
    when the same call also had to choose a tool, and it degraded again when
    one prompt taught two syntaxes. So instead of asking it to decide, look
    at what it produced: comparisons, arithmetic operators or numerals mean
    the question needs Z3, and it gets a second, equally narrow SMT-LIB
    translation call.

    Routing still never consults the question's wording — only the formulas.

    Args:
        formulas: Translated formula strings from the Prover9 pass.
        operators_only: Require an arithmetic operator and ignore bare
            numerals. Set when probing an unlabelled reply, where a stray
            digit is not evidence of arithmetic.

    Returns:
        True if the formulas use arithmetic Prover9 has no theory for.
    """
    pattern = _ARITHMETIC_OPERATOR_RE if operators_only else _ARITHMETIC_IN_FOL_RE
    return any(pattern.search(_FOL_CONNECTIVE_RE.sub(" ", f)) for f in formulas)


def classify_formalization(formulas: list[str]) -> FormulaTheory:
    """Classify theory use by parsing formula text, never question wording."""

    has_arithmetic = False
    has_uninterpreted = False
    for source in formulas:
        try:
            parse_fol(source.removesuffix(".").strip())
        except ParseError:
            try:
                expression = _parse_s_expression(source)
            except ValueError:
                return FormulaTheory.MALFORMED
            arithmetic, uninterpreted = _smt_theory_features(expression)
            has_arithmetic = has_arithmetic or arithmetic
            has_uninterpreted = has_uninterpreted or uninterpreted
        else:
            has_uninterpreted = True

    if has_arithmetic and has_uninterpreted:
        return FormulaTheory.MIXED
    if has_arithmetic:
        return FormulaTheory.ARITHMETIC
    return FormulaTheory.PURE_FOL


def normalize_syntax(formula: str) -> str:
    """Rewrite common non-Prover9 notation into Prover9/Mace4 syntax.

    Handles Unicode logic symbols (``∀ ∃ ∧ ∨ ¬ → ↔ ≠``) and ASCII dialect
    variants (``=> <=> || && ~ forall``) that the advisor LLM emits despite
    being instructed otherwise.  Also strips a trailing period, which
    Prover9 rejects mid-formula-list.

    Args:
        formula: Raw formula text from the LLM.

    Returns:
        The formula in Prover9-acceptable notation.
    """
    text = formula
    for src, dst in _SYNTAX_REWRITES:
        text = text.replace(src, dst)
    text = _MULTISPACE_RE.sub(" ", text).strip()
    return text.removesuffix(".").strip()


def normalize_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``plan`` with every formula field normalized."""
    cleaned = dict(plan)
    for key in _FORMULA_LIST_KEYS:
        value = cleaned.get(key)
        if isinstance(value, list):
            cleaned[key] = [
                normalize_syntax(f) if isinstance(f, str) else f for f in value
            ]
    for key in _FORMULA_STR_KEYS:
        value = cleaned.get(key)
        if isinstance(value, str):
            cleaned[key] = normalize_syntax(value)
    return cleaned


# ── Solver interface ────────────────────────────────────────────────────
class SolverBackend(Protocol):
    """Protocol for the solver backend that the advisor calls into.

    This is implemented by the ``_SolverBridge`` wired up in ``server.py``
    which delegates to the real ``LogicEngine`` and ``Mace4Wrapper``.
    """

    async def prove(
        self, premises: list[str], conclusion: str, *, timeout: int = 60
    ) -> dict[str, Any]: ...

    async def find_model(
        self,
        premises: list[str],
        *,
        domain_size: int | None = None,
        timeout: int = 60,
    ) -> dict[str, Any]: ...

    async def find_counterexample(
        self,
        premises: list[str],
        conclusion: str,
        *,
        domain_size: int | None = None,
        timeout: int = 60,
    ) -> dict[str, Any]: ...

    async def check_well_formed(self, statements: list[str]) -> dict[str, Any]: ...

    async def check_contingency(self, formula: str) -> dict[str, Any]: ...

    async def prove_arithmetic(
        self,
        premises: list[str],
        conclusion: str,
        variables: dict[str, str] | None = None,
        functions: dict[str, list[str]] | None = None,
    ) -> dict[str, Any]: ...

    async def check_satisfiable(
        self,
        constraints: list[str],
        variables: dict[str, str] | None = None,
        functions: dict[str, list[str]] | None = None,
    ) -> dict[str, Any]: ...


# ── Result dataclass ────────────────────────────────────────────────────
@dataclass(frozen=True)
class AdvisorResult:
    """Complete result from an advisor solve cycle."""

    answer: str
    """Natural-language answer for the client."""

    formalization: dict[str, Any]
    """The structured plan the LLM produced (tool, premises, etc.)."""

    solver_output: dict[str, Any]
    """Raw output from the solver tool."""

    steps: list[str] = field(default_factory=list)
    """Human-readable log of what the advisor did."""

    status: EpistemicStatus = EpistemicStatus.RESOURCE_LIMIT
    """How much the solver result establishes."""

    @property
    def verified(self) -> bool:
        """Whether the status represents a machine-checked decision.

        ``False`` means the answer is NOT machine-checked — the formalization
        failed validation, or the solver errored.  Callers must not present an
        unverified answer as a proof.
        """

        return self.status in {
            EpistemicStatus.PROVED,
            EpistemicStatus.REFUTED,
            EpistemicStatus.SATURATED_NO_PROOF,
        }


# ── System prompts ──────────────────────────────────────────────────────
_FORMALIZE_SYSTEM = """\
You are a formal logic expert embedded inside the mcp-logic solver. Your job \
is to take a natural-language logic question and produce a STRUCTURED JSON \
plan that specifies exactly which solver tool to call and with what arguments.

## Available Tools (pick ONE)

1. **prove** — Prove that a conclusion follows from premises.
   Output: {"tool": "prove", "premises": [...], "conclusion": "..."}

2. **find_model** — Find a finite model where all premises are true.
   Output: {"tool": "find_model", "premises": [...], "domain_size": N_or_null}

3. **find_counterexample** — Find a world where premises are true but conclusion is false.
   Output: {"tool": "find_counterexample", "premises": [...], "conclusion": "...", "domain_size": N_or_null}

4. **check_contingency** — Check if a propositional formula is tautology/contradiction/contingent.
   Output: {"tool": "check_contingency", "formula": "..."}

5. **check_well_formed** — Just validate syntax.
   Output: {"tool": "check_well_formed", "statements": [...]}

## Prover9/Mace4 Syntax Rules (MUST follow)
- Predicates and functions: **lowercase** — human(x), mortal(x), father(x,y)
- Variables: **lowercase single letters** — x, y, z, u, v, w
- Constants: **lowercase** — socrates, zero, c1
- Universal: all x (P(x) -> Q(x))
- Existential: exists x (P(x) & Q(x))
- Connectives: -> (implies), <-> (iff), & (and), | (or), - (not)
- Equality: =, inequality: !=
- Quantifiers MUST scope with parentheses
- Do NOT end formulas with periods

## Output Format
Return ONLY valid JSON. No markdown, no explanation, no code fences. Just the \
JSON object. If the question doesn't make sense as a logic problem, return:
{"tool": "none", "reason": "explanation"}
"""

_INTERPRET_SYSTEM = """\
You are a formal logic expert. You just ran a solver on the user's question. \
Now interpret the solver output and give a clear, concise answer in plain English.

Rules:
- State the answer first (yes/no/the formula is X).
- Then briefly explain the proof or counterexample.
- If a proof was found, summarize the key steps.
- If a counterexample was found, describe the model that disproves it.
- If the output contains a "countermodel", the conclusion does NOT follow:
  say so, then describe that concrete world in plain language — it is the
  most useful part of the answer.
- If the solver failed or timed out, explain why and suggest what to try next.
- Keep it under 200 words unless the proof is genuinely complex.
- Reference the original question in your answer.
"""

# The formalization prompt is deliberately shaped like the model's training
# task — numbered-line translation, not JSON authoring.  Measured on this
# model: asking for a JSON tool-plan gets the solver to accept 3/9 outputs,
# adding worked examples 6/9, and line-oriented translation 9/9.  The card
# also warns it has had "no instruction-following alignment work", so the
# narrowest possible task wins.
_FORMALIZE_LINES_SYSTEM = """\
You are a first-order logic translator. Translate the user's question into \
Prover9 formulas.

## Output format — one item per line, nothing else
PREMISE: <formula>      (one line per premise; omit if there are none)
GOAL: <formula>         (the conclusion, only for prove/find_counterexample)
FORMULA: <formula>      (only for check_contingency)
DOMAIN: <integer>       (optional, only for find_model)

## Prover9 syntax
{syntax_rules}

## Examples

Question: All humans are mortal. Socrates is a human. Does it follow that Socrates is mortal?
PREMISE: all x (human(x) -> mortal(x))
PREMISE: human(socrates)
GOAL: mortal(socrates)

Question: All cats are animals. Some animals are dogs. Does it follow that some cats are dogs?
PREMISE: all x (cat(x) -> animal(x))
PREMISE: exists x (animal(x) & dog(x))
GOAL: exists x (cat(x) & dog(x))

Question: Is p or not p a tautology?
FORMULA: p | -p

Question: Is the formula 'q and not q' a tautology, a contradiction, or contingent?
FORMULA: q & -q

Question: Find a world where every element has a successor and no element is its own successor.
PREMISE: all x exists y (succ(x,y))
PREMISE: all x (-succ(x,x))

## Two rules that override everything else

1. TRANSLATE, DO NOT ANSWER. You are never being asked to decide the
   question — a separate solver does that. If asked "is this a tautology?",
   emit the FORMULA: line and stop. Writing "TAUTOLOGY" is WRONG.
2. NEVER write an English sentence after PREMISE:, GOAL: or FORMULA:.
   "All cats are animals" is WRONG; "all x (cat(x) -> animal(x))" is RIGHT.

If the question is not a logic problem at all, output exactly:
NONE
""".format(syntax_rules=PROVER9_SYNTAX_RULES)

_SMT_FORMALIZE_SYSTEM = """\
You are an SMT-LIB translator. The question involves ARITHMETIC, so \
translate it into SMT-LIB assertions for the Z3 solver.

## Output format — one item per line, nothing else
VAR: <name> <Int|Real|Bool>    (declare every variable you use)
PREMISE: <assertion>           (one line per premise; omit if none)
GOAL: <assertion>              (the claim to check; omit for pure "is this possible" questions)

## SMT-LIB syntax — PREFIX notation, operator first
- Comparison: (> x 0)  (<= x y)  (= x 3)
- Arithmetic: (+ x 1)  (* 2 x)  (- x y)  (mod x 3)
- Logic: (and a b)  (or a b)  (not a)  (=> a b)
- Numbers are bare: 0, 1, 42. Reals need a decimal point: 0.0, 1.5

## Examples

Question: If x is a positive integer, is 2x greater than x?
VAR: x Int
PREMISE: (> x 0)
GOAL: (> (* 2 x) x)

Question: Alice is at least 18. Is she at least 16?
VAR: age Int
PREMISE: (>= age 18)
GOAL: (>= age 16)

Question: Is there a number between 0 and 10 divisible by 3?
VAR: n Int
PREMISE: (> n 0)
PREMISE: (< n 10)
PREMISE: (= (mod n 3) 0)

## Rules

1. TRANSLATE, DO NOT ANSWER — the solver decides.
2. Never write infix like "x > 0"; write "(> x 0)".
3. NEVER use `exists` or `forall`. To ask whether some number satisfies
   constraints, declare it with VAR: and assert the constraints directly.
   For "is there an n between 0 and 10 divisible by 3", write
   `VAR: n Int` / `PREMISE: (> n 0)` / `PREMISE: (< n 10)` /
   `PREMISE: (= (mod n 3) 0)` — NOT `exists n (...)`.
4. Declare every variable you use with a VAR: line.

If it is not an arithmetic question, output NONE.
"""

_REPAIR_SYSTEM = """\
You are a formal logic expert. Your previous formalization was REJECTED — \
either the syntax validator or the solver refused it. Produce a corrected \
JSON plan.

## Prover9/Mace4 Syntax Rules (MUST follow)
- ASCII ONLY. Never use Unicode symbols (no forall/exists/and/or/not glyphs).
- Universal: all x (P(x) -> Q(x))     [the keyword is `all`, not `forall`]
- Existential: exists x (P(x) & Q(x))
- Connectives: -> (implies), <-> (iff), & (and), | (or), - (not)
- Predicates, functions, constants: lowercase — human(x), socrates
- Variables: lowercase x, y, z, u, v, w
- Equality: =, inequality: !=
- Quantifiers MUST scope with parentheses
- Do NOT end formulas with periods
- A predicate must be used with the SAME number of arguments everywhere

Return ONLY the corrected JSON object. No markdown, no explanation. If the \
problem cannot be expressed in this syntax, return:
{"tool": "none", "reason": "explanation"}
"""

_UNVERIFIED_NOTICE = (
    "The solver could not verify this question, so NO machine-checked answer "
    "is available. Reporting the failure rather than guessing, because an "
    "unverified guess from this tool would be indistinguishable from a proof."
)


class AdvisorDisabledError(Exception):
    """Raised when the advisor is queried but was disabled via CLI flag."""


class LogicAdvisor:
    """Agentic logic solver powered by a local reasoning LLM.

    The advisor operates as a 3-phase pipeline:

    1. **Formalize**: The LLM translates a natural-language question into
       a structured JSON plan (which tool, what premises, etc.).
    2. **Execute**: The server runs the actual solver with those params.
    3. **Interpret**: The LLM interprets the solver output and returns a
       clear, natural-language answer.

    The client model just asks a question and gets a complete solution.

    Args:
        solver: Backend implementing the :class:`SolverBackend` protocol.
        model_path: Absolute path to a GGUF file.  If ``None``, the Q8_0
            quantization is auto-downloaded from HuggingFace on first use.
        n_gpu_layers: Layers to offload to GPU (``-1`` = all).
        n_ctx: Context window size in tokens.
        enabled: If ``False``, all queries raise :class:`AdvisorDisabledError`.
    """

    def __init__(
        self,
        solver: SolverBackend,
        model_path: str | None = None,
        n_gpu_layers: int = -1,
        n_ctx: int = _DEFAULT_N_CTX,
        *,
        enabled: bool = True,
        cache_size: int = _DEFAULT_CACHE_SIZE,
        idle_unload_seconds: float | None = _DEFAULT_IDLE_UNLOAD_SECONDS,
    ) -> None:
        self._solver = solver
        self._model: Any | None = None
        self._model_path: str | None = model_path
        self._n_gpu_layers = n_gpu_layers
        self._n_ctx = n_ctx
        self._enabled = enabled
        self._load_lock = asyncio.Lock()
        # One llama.cpp context, and every call now clears its KV cache
        # first.  Two overlapping requests would therefore reset each
        # other's state mid-generation, so inference is serialised.  MCP
        # servers handle requests concurrently, so this is reachable.
        self._inference_lock = asyncio.Lock()
        self._cache_size = cache_size
        self._cache: OrderedDict[tuple[str, str], AdvisorResult] = OrderedDict()
        self._idle_unload_seconds = idle_unload_seconds
        self._idle_task: asyncio.Task[None] | None = None

    # ── Properties ──────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        """Whether the advisor is enabled."""
        return self._enabled

    @property
    def loaded(self) -> bool:
        """Whether the model is currently in memory."""
        return self._model is not None

    # ── Public API ──────────────────────────────────────────────────────

    async def ensure_model(self) -> None:
        """Download (if needed) and load the model into GPU/CPU memory.

        Safe to call multiple times — subsequent calls are no-ops.
        """
        if not self._enabled:
            raise AdvisorDisabledError(
                "The logic advisor is disabled (--no-advisor was passed). "
                "Remove the flag and restart the server to enable it."
            )
        if self._model is not None:
            return

        async with self._load_lock:
            if self._model is not None:
                return
            await asyncio.to_thread(self._load_model_sync)

    async def solve(
        self,
        question: str,
        context: str = "",
        *,
        use_cache: bool = True,
    ) -> AdvisorResult:
        """Solve a logic problem end-to-end.

        Repeat questions are served from an in-memory cache.  Decoding is
        greedy, so re-running an identical question would produce an
        identical answer at the cost of several seconds of GPU time.

        Args:
            question: Natural-language logic question from the client.
            context: Optional context (background knowledge, constraints,
                previous solver output to debug, etc.).
            use_cache: Set ``False`` to force a fresh solve.

        Returns:
            :class:`AdvisorResult` with the answer, formalization, and
            raw solver output.
        """
        key = (question, context)

        if use_cache and key in self._cache:
            self._cache.move_to_end(key)
            cached = self._cache[key]
            self._touch_idle_timer()
            return AdvisorResult(
                answer=cached.answer,
                formalization=cached.formalization,
                solver_output=cached.solver_output,
                steps=[*cached.steps, "(served from cache)"],
                status=cached.status,
            )

        result = await self._solve_uncached(question, context)

        if use_cache and self._cache_size > 0:
            self._cache[key] = result
            self._cache.move_to_end(key)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)

        self._touch_idle_timer()
        return result

    def clear_cache(self) -> None:
        """Forget every cached answer."""
        self._cache.clear()

    async def _solve_uncached(
        self,
        question: str,
        context: str = "",
    ) -> AdvisorResult:
        """Run the full pipeline, ignoring the cache."""
        await self.ensure_model()
        steps: list[str] = []

        # ── Phase 1: Formalize ──────────────────────────────────────────
        steps.append("Phase 1: Formalizing question with TwIL-LM3...")
        user_msg = question
        if context:
            user_msg = f"{question}\n\n### Context\n{context}"

        # ONE narrow translation call, then route on the parsed formulas.
        # Question wording is deliberately absent from theory selection: a
        # digit in prose is not arithmetic, while a mixed quantified formula
        # may require it even when the prose uses no arithmetic keyword.
        lines = await self._llm_call(
            system=_FORMALIZE_LINES_SYSTEM,
            user=user_msg,
            max_tokens=_DEFAULT_MAX_TOKENS,
        )
        translated_formulas = [
            value
            for label, value in _LINE_RE.findall(_strip_think_blocks(lines))
            if label.upper() in {"PREMISE", "GOAL", "FORMULA", "STATEMENT"}
        ]
        theory = classify_formalization(translated_formulas)
        smt_attempted = False

        if theory not in {
            FormulaTheory.ARITHMETIC,
            FormulaTheory.MIXED,
        } and needs_smt_retranslation(translated_formulas):
            # The Prover9 pass reached for arithmetic it cannot express.
            # Re-translate with the dedicated SMT-LIB prompt rather than
            # sending `x > 0` to a prover with no theory of arithmetic.
            steps.append(
                "Translation used arithmetic Prover9 cannot express — "
                "re-translating as SMT-LIB."
            )
            lines = await self._llm_call(
                system=_SMT_FORMALIZE_SYSTEM,
                user=user_msg,
                max_tokens=_DEFAULT_MAX_TOKENS,
            )
            translated_formulas = [
                value
                for label, value in _LINE_RE.findall(_strip_think_blocks(lines))
                if label.upper() in {"PREMISE", "GOAL", "FORMULA", "STATEMENT"}
            ]
            theory = classify_formalization(translated_formulas)

        if theory in {FormulaTheory.ARITHMETIC, FormulaTheory.MIXED}:
            steps.append(f"Parsed formula theory is {theory.value} — routing to Z3.")
            plan = parse_smt_formalization(lines)
            smt_attempted = True
        else:
            plan = normalize_plan(parse_formalization(lines, question=question))

        if plan.get("tool") == "none" and not smt_attempted:
            # A first-order translation that produced nothing usable is not
            # proof the question is unformalizable — on arithmetic questions
            # this model often answers "NONE" or with a bare expression,
            # because the Prover9 syntax it was handed genuinely cannot say
            # "x > 0". Spend one more narrow call on the SMT-LIB prompt
            # before concluding there is nothing here.
            steps.append(
                "First-order translation yielded nothing usable — retrying "
                "as SMT-LIB before giving up."
            )
            lines = await self._llm_call(
                system=_SMT_FORMALIZE_SYSTEM,
                user=user_msg,
                max_tokens=_DEFAULT_MAX_TOKENS,
            )
            smt_plan = parse_smt_formalization(lines)
            if smt_plan.get("tool") not in (None, "none"):
                plan = smt_plan
                steps.append(f"SMT-LIB retry succeeded: {plan['tool']}.")
        steps.append(f"Formalization: {json.dumps(plan, indent=2)}")

        if plan.get("tool") == "none":
            return AdvisorResult(
                answer=plan.get(
                    "reason", "Unable to formalize this as a logic problem."
                ),
                formalization=plan,
                solver_output={},
                steps=steps,
                status=EpistemicStatus.MALFORMED,
            )

        # ── Phase 1b: Validate, and repair once if the syntax is bad ────
        problem = await self._validation_error(plan)
        if problem is not None:
            steps.append(f"Validation rejected the formalization: {problem}")
            steps.append("Phase 1b: Asking the model to repair the formalization...")
            plan = await self._repair_plan(user_msg, plan, problem)
            steps.append(f"Repaired formalization: {json.dumps(plan, indent=2)}")

            if plan.get("tool") == "none":
                return AdvisorResult(
                    answer=f"{_UNVERIFIED_NOTICE}\n\nReason: "
                    + plan.get("reason", "the question could not be formalized."),
                    formalization=plan,
                    solver_output={},
                    steps=steps,
                    status=EpistemicStatus.MALFORMED,
                )

            problem = await self._validation_error(plan)
            if problem is not None:
                steps.append(f"Repair failed validation as well: {problem}")
                return AdvisorResult(
                    answer=(
                        f"{_UNVERIFIED_NOTICE}\n\nThe question could not be "
                        f"translated into valid Prover9 syntax after one repair "
                        f"attempt. Last validation error: {problem}"
                    ),
                    formalization=plan,
                    solver_output={
                        "validation_error": problem,
                        "status": EpistemicStatus.MALFORMED,
                    },
                    steps=steps,
                    status=EpistemicStatus.MALFORMED,
                )

        # ── Phase 2: Execute ────────────────────────────────────────────
        tool_name = plan["tool"]
        steps.append(f"Phase 2: Running solver tool '{tool_name}'...")

        solver_output = await self._run_solver(plan)
        steps.append(f"Solver result: {json.dumps(solver_output, indent=2)[:500]}")

        # ── Phase 2b: Repair against the solver's own parser ─────────────
        # The syntax validator is permissive — it accepts plain English and
        # arithmetic Prover9 cannot parse — so a clean validation says very
        # little.  Prover9 itself is the only authoritative parser, which
        # makes its rejection the signal actually worth repairing against.
        if _is_solver_error(solver_output):
            solver_reason = (
                solver_output.get("error")
                or solver_output.get("reason")
                or "unknown solver error"
            )
            steps.append(f"Solver rejected the formalization: {solver_reason}")
            steps.append("Phase 2b: Repairing against the solver error...")
            repaired = await self._repair_plan(user_msg, plan, str(solver_reason))
            steps.append(f"Repaired formalization: {json.dumps(repaired, indent=2)}")

            if repaired.get("tool") not in (None, "none"):
                plan = repaired
                solver_output = await self._run_solver(plan)
                steps.append(
                    f"Solver result after repair: "
                    f"{json.dumps(solver_output, indent=2)[:500]}"
                )

        if _is_undecided(solver_output):
            reason = solver_output.get("reason", "the solver could not decide")
            steps.append(f"Solver returned no verdict: {reason}")
            return AdvisorResult(
                answer=f"{_UNVERIFIED_NOTICE}\n\n{reason}",
                formalization=plan,
                solver_output=solver_output,
                steps=steps,
                status=EpistemicStatus(solver_output["status"]),
            )

        # A solver error means there is no verdict to interpret.  Letting the
        # LLM answer anyway produces a confident, unverified guess — exactly
        # the failure this tool exists to prevent.
        if _is_solver_error(solver_output):
            reason = (
                solver_output.get("error")
                or solver_output.get("reason")
                or "unknown solver error"
            )
            steps.append(f"Solver failed; refusing to answer unverified. {reason}")
            return AdvisorResult(
                answer=(
                    f"{_UNVERIFIED_NOTICE}\n\nSolver error: {reason}\n\n"
                    f"Formalization attempted:\n"
                    f"{json.dumps(plan, indent=2)}"
                ),
                formalization=plan,
                solver_output=solver_output,
                steps=steps,
                status=EpistemicStatus(solver_output["status"]),
            )

        # ── Phase 2c: Turn "unprovable" into a concrete countermodel ────
        # "The conclusion does not follow" is a real verdict but an
        # unsatisfying one.  Mace4 can usually exhibit a world where the
        # premises hold and the conclusion fails, which turns a bare "No"
        # into something the user can inspect and argue with.
        if plan.get("tool") == "prove" and solver_output.get("result") == "unprovable":
            steps.append("Unprovable — asking Mace4 for a countermodel...")
            counter = await self._solver.find_counterexample(
                premises=plan.get("premises", []),
                conclusion=plan.get("conclusion", ""),
            )
            if not _is_solver_error(counter):
                solver_output = {**solver_output, "countermodel": counter}
                steps.append(
                    f"Countermodel search: {counter.get('result', 'no result')}"
                )

        # ── Phase 3: Interpret ──────────────────────────────────────────
        steps.append("Phase 3: Interpreting results with TwIL-LM3...")
        interpret_prompt = (
            f"## Original Question\n{question}\n\n"
            f"## Formalization\n```json\n{json.dumps(plan, indent=2)}\n```\n\n"
            f"## Solver Output\n```json\n{json.dumps(solver_output, indent=2)}\n```"
        )

        answer = await self._llm_call(
            system=_INTERPRET_SYSTEM,
            user=interpret_prompt,
            max_tokens=_DEFAULT_MAX_TOKENS,
        )
        steps.append("Done.")

        return AdvisorResult(
            answer=answer,
            formalization=plan,
            solver_output=solver_output,
            steps=steps,
            status=EpistemicStatus(solver_output["status"]),
        )

    async def query(
        self,
        question: str,
        context: str = "",
    ) -> str:
        """Simple string-in, string-out interface for the MCP handler.

        Delegates to :meth:`solve` and returns just the answer text.
        """
        result = await self.solve(question, context)
        return result.answer

    async def unload(self) -> None:
        """Release the model from memory."""
        if self._idle_task is not None:
            self._idle_task.cancel()
            self._idle_task = None
        if self._model is not None:
            logger.info("Unloading logic advisor model from memory")
            self._model = None

    # ── Private: idle unloading ─────────────────────────────────────────

    def _touch_idle_timer(self) -> None:
        """Restart the idle countdown after activity.

        The model is ~3.3 GB of VRAM and this tool may go untouched for long
        stretches, so it is dropped after a quiet period and lazily reloaded
        on the next query (about a second from page cache).
        """
        if self._idle_unload_seconds is None:
            return

        if self._idle_task is not None:
            self._idle_task.cancel()

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover - no loop outside async use
            return

        self._idle_task = loop.create_task(self._unload_after_idle())

    async def _unload_after_idle(self) -> None:
        """Wait out the idle window, then release the model."""
        idle_seconds = self._idle_unload_seconds
        if idle_seconds is None:  # pragma: no cover - guarded by the caller
            return

        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.sleep(idle_seconds)
            async with self._inference_lock:
                if self._model is not None:
                    logger.info(
                        "Advisor idle for %.0fs — unloading model from memory",
                        idle_seconds,
                    )
                    self._model = None
            self._idle_task = None

    # ── Private: LLM ────────────────────────────────────────────────────

    async def _llm_call(
        self,
        system: str,
        user: str,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        temperature: float = _DEFAULT_TEMPERATURE,
    ) -> str:
        """Run a single LLM chat completion, stripping think blocks."""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        logger.debug("LLM call (max_tokens=%d): %s", max_tokens, user[:200])

        async with self._inference_lock:
            response = await asyncio.to_thread(
                self._create_chat_completion,
                messages,
                max_tokens,
                temperature,
            )
        raw = response["choices"][0]["message"]["content"]
        cleaned = _strip_think_blocks(raw)
        logger.debug("LLM response (%d chars): %s", len(cleaned), cleaned[:300])
        return cleaned

    # ── Private: Validation & repair ────────────────────────────────────

    async def _validation_error(self, plan: dict[str, Any]) -> str | None:
        """Syntax-check a plan's formulas.

        Args:
            plan: A normalized formalization plan.

        Returns:
            A human-readable error string, or ``None`` if the plan's
            formulas are well formed (or carry nothing to check).
        """
        # SMT plans are SMT-LIB, not Prover9 — the first-order validator
        # would reject every one of them.  Z3's own parser is the check.
        if plan.get("tool") in _SMT_TOOLS:
            return None

        formulas = self._plan_formulas(plan)
        if not formulas:
            return None

        try:
            report = await self._solver.check_well_formed(formulas)
        except Exception as exc:  # noqa: BLE001 - validation must never crash solve()
            logger.warning("Syntax validation raised: %s", exc)
            return None

        if report.get("valid", True):
            return None

        problems: list[str] = []
        for entry in report.get("formula_results", []):
            if not entry.get("valid", True):
                errors = "; ".join(entry.get("errors", [])) or "invalid syntax"
                problems.append(f"{entry.get('formula', '?')} -> {errors}")
        problems.extend(report.get("set_errors", []))
        return " | ".join(problems) or "formula set rejected by the validator"

    @staticmethod
    def _plan_formulas(plan: dict[str, Any]) -> list[str]:
        """Collect every formula string a plan will hand to the solver."""
        formulas: list[str] = []
        for key in _FORMULA_LIST_KEYS:
            value = plan.get(key)
            if isinstance(value, list):
                formulas.extend(f for f in value if isinstance(f, str) and f)
        for key in _FORMULA_STR_KEYS:
            value = plan.get(key)
            # check_contingency uses propositional syntax the first-order
            # validator does not accept, so leave `formula` alone.
            if key != "formula" and isinstance(value, str) and value:
                formulas.append(value)
        return formulas

    async def _repair_plan(
        self,
        original_question: str,
        bad_plan: dict[str, Any],
        problem: str,
    ) -> dict[str, Any]:
        """Ask the model to fix a rejected formalization (single attempt).

        The repair speaks the same labelled-line format as the initial
        formalization — switching the model to a different output shape
        mid-pipeline is what the ablation showed it handles worst.
        """
        tool = str(bad_plan.get("tool", "prove"))
        is_smt = tool in _SMT_TOOLS
        syntax = "SMT-LIB prefix" if is_smt else "Prover9"
        prompt = (
            f"## Original Question\n{original_question}\n\n"
            f"## Rejected Translation\n{_plan_to_lines(bad_plan)}\n\n"
            f"## Why It Was Rejected\n{problem}\n\n"
            f"Write the corrected lines. Every formula must be {syntax} "
            f"syntax, never English."
        )
        raw = await self._llm_call(
            system=_SMT_FORMALIZE_SYSTEM if is_smt else _FORMALIZE_LINES_SYSTEM,
            user=prompt,
            max_tokens=_DEFAULT_MAX_TOKENS,
        )
        if is_smt:
            return parse_smt_formalization(raw)
        return normalize_plan(parse_formalization(raw, tool=tool))

    # ── Private: Solver dispatch ────────────────────────────────────────

    async def _run_solver(self, plan: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a formalized plan to the appropriate solver."""
        tool = plan.get("tool", "")

        try:
            if tool == "prove":
                result = await self._solver.prove(
                    premises=plan.get("premises", []),
                    conclusion=plan.get("conclusion", ""),
                )
                return with_status(result, operation=tool)

            elif tool == "find_model":
                result = await self._solver.find_model(
                    premises=plan.get("premises", []),
                    domain_size=plan.get("domain_size"),
                )
                return with_status(result, operation=tool)

            elif tool == "find_counterexample":
                result = await self._solver.find_counterexample(
                    premises=plan.get("premises", []),
                    conclusion=plan.get("conclusion", ""),
                    domain_size=plan.get("domain_size"),
                )
                return with_status(result, operation=tool)

            elif tool == "check_contingency":
                result = await self._solver.check_contingency(
                    formula=plan.get("formula", ""),
                )
                return with_status(result, operation=tool)

            elif tool == "check_well_formed":
                result = await self._solver.check_well_formed(
                    statements=plan.get("statements", []),
                )
                return with_status(result, operation="validate")

            elif tool == "prove_arithmetic":
                result = await self._solver.prove_arithmetic(
                    premises=plan.get("premises", []),
                    conclusion=plan.get("conclusion", ""),
                    variables=plan.get("variables", {}),
                    functions=plan.get("functions", {}),
                )
                return with_status(result, operation=tool)

            elif tool == "check_satisfiable":
                result = await self._solver.check_satisfiable(
                    constraints=plan.get("constraints", []),
                    variables=plan.get("variables", {}),
                    functions=plan.get("functions", {}),
                )
                return with_status(result, operation=tool)

            else:
                return {
                    "result": "error",
                    "status": EpistemicStatus.MALFORMED,
                    "error": f"Unknown tool in plan: {tool}",
                }

        except Exception as exc:
            logger.error("Solver execution failed: %s", exc, exc_info=True)
            return {
                "result": "error",
                "status": EpistemicStatus.RESOURCE_LIMIT,
                "error": str(exc),
                "type": type(exc).__name__,
            }

    # ── Private: Plan parsing ───────────────────────────────────────────

    @staticmethod
    def _parse_plan(raw_text: str) -> dict[str, Any]:
        """Extract JSON from the LLM's formalization output.

        The model is instructed to output pure JSON, but may occasionally
        wrap it in markdown code fences.  This handles both cases.
        """
        text = raw_text.strip()

        # Strip markdown code fences if present.
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first line (```json) and last line (```)
            lines = [line for line in lines if not line.strip().startswith("```")]
            text = "\n".join(lines).strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Mine the reasoning text for embedded objects.  Take the LAST
            # parseable one: the model habitually sketches candidate objects
            # while thinking and states its real answer at the end.  A plan
            # must name a tool, so objects without one are ignored — that
            # skips illustrative fragments quoted from the prompt.
            candidates = _iter_json_objects(text)
            fallback: dict[str, Any] | None = None
            for span in reversed(candidates):
                try:
                    parsed = json.loads(span)
                except json.JSONDecodeError:
                    continue
                if not isinstance(parsed, dict):
                    continue
                if "tool" in parsed:
                    return parsed
                if fallback is None:
                    fallback = parsed
            if fallback is not None:
                return fallback

            logger.warning("Failed to parse LLM plan as JSON: %s", text[:300])
            return {
                "tool": "none",
                "reason": f"Failed to parse formalization output: {text[:200]}",
            }

    # ── Private: Model management ───────────────────────────────────────

    def _resolve_model_path(self) -> str:
        """Return the path to the GGUF file, downloading if necessary."""
        if self._model_path:
            path = Path(self._model_path)
            if not path.exists():
                raise FileNotFoundError(
                    f"Specified model path does not exist: {self._model_path}"
                )
            return str(path)

        # Already cached from a previous run (or by setup-advisor.sh)?
        # Check before touching the network so the advisor works offline.
        cached = _DEFAULT_CACHE_DIR / _GGUF_FILENAME
        if cached.exists():
            logger.info("Using cached advisor model: %s", cached)
            return str(cached)

        # Auto-download from HuggingFace.
        try:
            from huggingface_hub import hf_hub_download  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError(
                "huggingface-hub is required for auto-downloading the advisor "
                "model.  Install with: uv pip install huggingface-hub"
            ) from exc

        logger.info(
            "Downloading %s from %s (one-time, ~3.3 GB)…",
            _GGUF_FILENAME,
            _HF_REPO_ID,
        )
        _DEFAULT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = hf_hub_download(
            repo_id=_HF_REPO_ID,
            filename=_GGUF_FILENAME,
            revision=_HF_REVISION,
            local_dir=str(_DEFAULT_CACHE_DIR),
        )
        logger.info("Model downloaded to %s", path)
        return path

    def _load_model_sync(self) -> None:
        """Synchronous model load — called via ``asyncio.to_thread``."""
        try:
            from llama_cpp import Llama  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError(
                "llama-cpp-python is required for the logic advisor.  "
                'Install with: CMAKE_ARGS="-DGGML_CUDA=on" '
                "uv pip install llama-cpp-python"
            ) from exc

        model_path = self._resolve_model_path()
        logger.info(
            "Loading logic advisor model: %s (gpu_layers=%d, n_ctx=%d)",
            model_path,
            self._n_gpu_layers,
            self._n_ctx,
        )
        self._model = Llama(
            model_path=model_path,
            n_ctx=self._n_ctx,
            n_gpu_layers=self._n_gpu_layers,
            verbose=False,
        )
        logger.info("Logic advisor model loaded successfully")

    def _create_chat_completion(
        self,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        """Run chat completion synchronously — called via to_thread.

        ``repeat_penalty`` is pinned to 1.0 deliberately. llama.cpp defaults
        it to 1.1, but the TwIL-LM3 model card calls ``repetition_penalty =
        1.0`` "load-bearing": a 1.1 penalty produced apparent 20-point
        benchmark swings that were pure decoding artefact. A reasoning model
        legitimately repeats tokens while working through a proof, and
        penalising that derails the ``<think>`` block.
        """
        model = self._model
        if model is None:
            raise RuntimeError("Logic advisor model is not loaded")

        # Reset generation state before every call.  llama.cpp reuses the KV
        # cache via longest-prefix matching, and every advisor prompt shares
        # the same long system-prompt prefix.  Left alone, the FIRST call on a
        # fresh model returns correct FOL and every subsequent one degrades to
        # echoing the question back as plain English — deterministically, so
        # it reads like a model-quality problem rather than stale state.  The
        # advisor is long-lived inside the MCP server, so this hit every query
        # after the first.
        self._reset_model_state()

        return model.create_chat_completion(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            repeat_penalty=_REPEAT_PENALTY,
        )

    def _reset_model_state(self) -> None:
        """Clear token history and KV cache so each call starts clean."""
        model = self._model
        if model is None:
            return

        reset = getattr(model, "reset", None)
        if callable(reset):
            reset()

        # Belt and braces: drop the KV cache itself.  The private handle moved
        # between llama-cpp-python versions, so probe rather than assume.
        ctx = getattr(model, "_ctx", None)
        for name in ("kv_cache_clear", "kv_self_clear"):
            clear = getattr(ctx, name, None)
            if callable(clear):
                clear()
                break


_SMT_TOOLS = frozenset({"prove_arithmetic", "check_satisfiable"})

_VALID_TOOLS = frozenset(
    {
        "prove",
        "find_model",
        "find_counterexample",
        "check_contingency",
        "check_well_formed",
    }
)

# "PREMISE: all x (p(x))" → ("premise", "all x (p(x))")
_LINE_RE = re.compile(
    r"^\s*(PREMISE|GOAL|FORMULA|DOMAIN|STATEMENT)\s*:\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


# Questions that explicitly ask for a world/model rather than a proof.
_MODEL_REQUEST_RE = re.compile(
    r"\b(find|give|show|construct|is there)\b[^.?]*\b"
    r"(model|world|interpretation|structure|example)\b|\bsatisfiab|\bconsistent\b",
    re.IGNORECASE,
)
_COUNTEREXAMPLE_REQUEST_RE = re.compile(
    r"\bcounter-?example\b|\bdisprove\b|\brefute\b", re.IGNORECASE
)


def infer_tool(question: str, plan_parts: dict[str, Any]) -> str:
    """Choose a solver tool from the question and the translated formulas.

    Deliberately deterministic rather than a second LLM call.  A separate
    "name the tool" request measured worse than useless on this model: it
    opens a ``<think>`` block before answering, so any budget small enough to
    be cheap truncates before the answer, and every question came back
    ``none``.  The translation already carries the answer — a GOAL means
    there is something to prove, a bare FORMULA means propositional work,
    premises alone mean model finding — so read it from there and use the
    question only to distinguish the two Mace4 modes.

    Args:
        question: The original natural-language question.
        plan_parts: Parsed line output with ``premises``/``goal``/``formula``.

    Returns:
        One of :data:`_VALID_TOOLS`.
    """
    if plan_parts.get("formula"):
        return "check_contingency"

    has_goal = bool(plan_parts.get("goal"))
    if has_goal:
        if _COUNTEREXAMPLE_REQUEST_RE.search(question):
            return "find_counterexample"
        return "prove"

    if plan_parts.get("premises"):
        if _MODEL_REQUEST_RE.search(question):
            return "find_model"
        # Premises with nothing to prove: satisfiability is the only
        # question left worth asking.
        return "find_model"

    return "none"


def parse_formalization(raw: str, question: str = "", tool: str = "") -> dict[str, Any]:
    """Turn labelled translation lines into a solver plan.

    Falls back to JSON extraction, since the model occasionally answers in
    the JSON shape rather than the line shape.

    Args:
        raw: The model's formalization reply.
        question: Original question, used to pick between Mace4 modes.
        tool: Force a specific tool instead of inferring one (used by the
            repair path, which must not switch tools mid-flight).

    Returns:
        A plan dict, or ``{"tool": "none", ...}`` if nothing usable was found.
    """
    text = _strip_think_blocks(raw)

    premises: list[str] = []
    goal = ""
    formula = ""
    domain: int | None = None

    for label, value in _LINE_RE.findall(text):
        label = label.upper()
        if label in {"PREMISE", "STATEMENT"}:
            premises.append(value)
        elif label == "GOAL":
            goal = value
        elif label == "FORMULA":
            formula = value
        elif label == "DOMAIN":
            try:
                domain = int(value)
            except ValueError:
                domain = None

    if not premises and not goal and not formula:
        # The model ignored the line format — try the JSON shape.
        fallback = LogicAdvisor._parse_plan(text)
        if fallback.get("tool") not in (None, "none"):
            return fallback
        if re.search(r"^\s*NONE\s*$", text, re.IGNORECASE | re.MULTILINE):
            return {
                "tool": "none",
                "reason": "This is not a logic problem the solver can take.",
            }
        return {
            "tool": "none",
            "reason": (
                "The question could not be translated into logic. The model "
                f"replied: {text[:200]}"
            ),
        }

    tool = tool or infer_tool(
        question, {"premises": premises, "goal": goal, "formula": formula}
    )

    plan: dict[str, Any] = {"tool": tool}
    if tool == "check_contingency":
        plan["formula"] = formula or goal or (premises[0] if premises else "")
    elif tool == "check_well_formed":
        plan["statements"] = premises or ([goal] if goal else [])
    else:
        plan["premises"] = premises
        if tool in {"prove", "find_counterexample"}:
            plan["conclusion"] = goal
        if tool == "find_model" and domain is not None:
            plan["domain_size"] = domain

    # prove/find_counterexample without a goal is not runnable.
    if tool in {"prove", "find_counterexample"} and not plan.get("conclusion"):
        return {
            "tool": "none",
            "reason": "No GOAL line was produced, so there is nothing to prove.",
        }

    return plan


# "VAR: x Int" → ("x", "Int")
_VAR_RE = re.compile(
    r"^\s*VAR\s*:\s*(\w+)\s+(Int|Real|Bool)\s*$", re.IGNORECASE | re.MULTILINE
)
_PRED_RE = re.compile(
    r"^\s*PRED\s*:\s*(\w+)(?:\s+((?:Int|Real|Bool)(?:\s+(?:Int|Real|Bool))*))?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_FUN_RE = re.compile(
    r"^\s*FUN\s*:\s*(\w+)\s*(.*?)\s*->\s*(Int|Real|Bool)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


# SMT-LIB operators and keywords — anything else in an assertion is a
# variable that needs declaring.
_SMT_RESERVED = frozenset(
    {
        "and",
        "or",
        "not",
        "xor",
        "ite",
        "let",
        "distinct",
        "true",
        "false",
        "forall",
        "exists",
        "div",
        "mod",
        "rem",
        "abs",
        "to_real",
        "to_int",
        "is_int",
        "Int",
        "Real",
        "Bool",
        "assert",
        "declare-const",
        "declare-fun",
    }
)
_SMT_SORTS = frozenset({"Int", "Real", "Bool"})
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.\-]*")
_DECIMAL_RE = re.compile(r"\d+\.\d+")


def infer_variables(
    constraints: list[str],
    declared: dict[str, str] | None = None,
    functions: dict[str, list[str]] | None = None,
) -> dict[str, str]:
    """Guess declarations for variables the model forgot to declare.

    The model frequently emits correct constraints but omits the ``VAR:``
    lines, and Z3 then rejects the whole script over an undeclared
    constant.  Every free identifier is recoverable from the constraints
    themselves, so recover it rather than failing the query.

    Sort is inferred globally: ``Real`` if any decimal literal appears,
    otherwise ``Int``.  Wrong only in mixed-sort problems, which the model
    does not produce in practice.

    Args:
        constraints: SMT-LIB assertion strings.
        declared: Declarations the model did provide; these win.

    Returns:
        Merged declarations covering every identifier used.
    """
    result = dict(declared or {})
    joined = " ".join(constraints)
    sort = "Real" if _DECIMAL_RE.search(joined) else "Int"

    function_names = set(functions or {})

    def collect(expression: object, bound: frozenset[str]) -> set[str]:
        if isinstance(expression, str):
            if (
                _IDENT_RE.fullmatch(expression)
                and expression not in _SMT_RESERVED
                and expression not in _SMT_SORTS
                and expression not in bound
                and expression not in function_names
            ):
                return {expression}
            return set()
        if not isinstance(expression, list) or not expression:
            return set()
        head = expression[0]
        if head in {"forall", "exists"} and len(expression) >= 3:
            binders = expression[1]
            names = {
                binder[0]
                for binder in binders
                if isinstance(binder, list) and binder and isinstance(binder[0], str)
            }
            found: set[str] = set()
            for child in expression[2:]:
                found.update(collect(child, bound | names))
            return found
        found = set()
        for child in expression[1:]:
            found.update(collect(child, bound))
        return found

    inferred: set[str] = set()
    for constraint in constraints:
        try:
            inferred.update(collect(_parse_s_expression(constraint), frozenset()))
        except ValueError:
            for token in _IDENT_RE.findall(constraint):
                if token not in _SMT_RESERVED and token not in function_names:
                    inferred.add(token)
    for token in inferred:
        result.setdefault(token, sort)
    return result


def parse_smt_formalization(raw: str) -> dict[str, Any]:
    """Parse ``VAR:``/``PREMISE:``/``GOAL:`` lines into an SMT plan.

    Returns:
        A plan dict with ``tool`` set to ``prove_arithmetic`` (when a GOAL
        was given) or ``check_satisfiable``, or ``{"tool": "none"}``.
    """
    text = _strip_think_blocks(raw)

    variables = {name: sort.capitalize() for name, sort in _VAR_RE.findall(text)}
    functions: dict[str, list[str]] = {}
    for name, sorts in _PRED_RE.findall(text):
        args = [sort.capitalize() for sort in sorts.split()] if sorts else []
        functions[name] = [*args, "Bool"]
    for name, args, result_sort in _FUN_RE.findall(text):
        arg_sorts = [sort.capitalize() for sort in args.split()] if args else []
        functions[name] = [*arg_sorts, result_sort.capitalize()]
    premises: list[str] = []
    goal = ""

    for label, value in _LINE_RE.findall(text):
        label = label.upper()
        if label in {"PREMISE", "STATEMENT"}:
            premises.append(value)
        elif label == "GOAL":
            goal = value

    if not premises and not goal:
        return {
            "tool": "none",
            "reason": (
                "The question could not be translated into arithmetic "
                f"constraints. The model replied: {text[:200]}"
            ),
        }

    if goal:
        return {
            "tool": "prove_arithmetic",
            "premises": premises,
            "conclusion": goal,
            "variables": infer_variables([*premises, goal], variables, functions),
            "functions": functions,
        }
    return {
        "tool": "check_satisfiable",
        "constraints": premises,
        "variables": infer_variables(premises, variables, functions),
        "functions": functions,
    }


def _plan_to_lines(plan: dict[str, Any]) -> str:
    """Render a plan back into the labelled-line format, for repair prompts."""
    lines: list[str] = []
    for name, sort in (plan.get("variables") or {}).items():
        lines.append(f"VAR: {name} {sort}")
    for name, signature in (plan.get("functions") or {}).items():
        *args, result = signature
        if result == "Bool":
            lines.append(f"PRED: {name} {' '.join(args)}".rstrip())
        else:
            lines.append(f"FUN: {name} {' '.join(args)} -> {result}".replace("  ", " "))
    for premise in (
        plan.get("premises") or plan.get("statements") or plan.get("constraints") or []
    ):
        lines.append(f"PREMISE: {premise}")
    if plan.get("conclusion"):
        lines.append(f"GOAL: {plan['conclusion']}")
    if plan.get("formula"):
        lines.append(f"FORMULA: {plan['formula']}")
    if plan.get("domain_size") is not None:
        lines.append(f"DOMAIN: {plan['domain_size']}")
    return "\n".join(lines) or "(nothing usable was produced)"


def _is_solver_error(output: dict[str, Any]) -> bool:
    """Whether solver output represents a failure rather than a verdict.

    A timeout or an exhausted search is a legitimate (if unhelpful) verdict
    the interpreter can explain.  A syntax error or an exception is not —
    there is nothing to interpret.
    """
    if not output:
        return True
    if "status" in output:
        return output.get("status") == EpistemicStatus.MALFORMED
    return bool(output.get("error")) or output.get("result") == "error"


def _is_undecided(output: dict[str, Any]) -> bool:
    """Whether the solver returned no verdict at all.

    Two statuses, neither of them a decision:

    * Z3 ``unknown`` — nonlinear arithmetic or quantifiers defeated it.
    * Prover9 ``inconclusive`` — the search stopped on a resource limit
      rather than saturating, so it is NOT evidence the conclusion is
      false (first-order validity is only semi-decidable).
    * Mace4 ``BOUNDED_NO_MODEL`` — the configured finite range was exhausted,
      but no complete-fragment bound licenses an absolute conclusion.

    Repairing the formalization would not help in any of these cases.
    """
    return output.get("status") in {
        EpistemicStatus.RESOURCE_LIMIT,
        EpistemicStatus.BOUNDED_NO_MODEL,
    }


def _strip_think_blocks(text: str) -> str:
    """Remove ``<think>…</think>`` reasoning blocks from model output.

    Closed blocks are removed outright.  An *unterminated* ``<think>`` is a
    different situation: the model never emitted the closing tag but usually
    did produce its answer inside the block, so dropping everything after the
    tag would throw the answer away.  Only the tag itself is removed, leaving
    the content for :meth:`LogicAdvisor._parse_plan` to mine.
    """
    cleaned = _THINK_RE.sub("", text)
    if "</think>" not in cleaned:
        cleaned = _OPEN_THINK_RE.sub("", cleaned)
    return cleaned.strip()


def _iter_json_objects(text: str) -> list[str]:
    r"""Return every balanced ``{...}`` span in ``text``, in order.

    A greedy ``\{.*\}`` regex spans from the first brace to the last, which
    swallows prose whenever the model shows an illustrative object before its
    real answer.  Brace matching (string- and escape-aware) finds each
    candidate separately instead.
    """
    spans: list[str] = []
    depth = 0
    start = -1
    in_string = False
    escaped = False

    for i, ch in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                spans.append(text[start : i + 1])
                start = -1

    return spans

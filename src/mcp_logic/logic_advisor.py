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
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    pass

logger = logging.getLogger("mcp_logic.logic_advisor")

# ── Constants ───────────────────────────────────────────────────────────
_HF_REPO_ID = "webAI-Official/TwIL-LM3"
_GGUF_FILENAME = "TwIL-LM3-Q8_0.gguf"
_DEFAULT_CACHE_DIR = Path.home() / ".cache" / "mcp-logic" / "models"

# Strip <think>…</think> reasoning blocks from output.
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)

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

    verified: bool = True
    """Whether the solver actually ran and returned a usable verdict.

    ``False`` means the answer is NOT machine-checked — the formalization
    failed validation, or the solver errored.  Callers must not present an
    unverified answer as a proof.
    """


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
- If the solver failed or timed out, explain why and suggest what to try next.
- Keep it under 200 words unless the proof is genuinely complex.
- Reference the original question in your answer.
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
        n_ctx: int = 4096,
        *,
        enabled: bool = True,
    ) -> None:
        self._solver = solver
        self._model: Any | None = None
        self._model_path: str | None = model_path
        self._n_gpu_layers = n_gpu_layers
        self._n_ctx = n_ctx
        self._enabled = enabled
        self._load_lock = asyncio.Lock()

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
    ) -> AdvisorResult:
        """Solve a logic problem end-to-end.

        Args:
            question: Natural-language logic question from the client.
            context: Optional context (background knowledge, constraints,
                previous solver output to debug, etc.).

        Returns:
            :class:`AdvisorResult` with the answer, formalization, and
            raw solver output.
        """
        await self.ensure_model()
        steps: list[str] = []

        # ── Phase 1: Formalize ──────────────────────────────────────────
        steps.append("Phase 1: Formalizing question with TwIL-LM3...")
        user_msg = question
        if context:
            user_msg = f"{question}\n\n### Context\n{context}"

        plan_json = await self._llm_call(
            system=_FORMALIZE_SYSTEM,
            user=user_msg,
            max_tokens=1024,
        )

        plan = normalize_plan(self._parse_plan(plan_json))
        steps.append(f"Formalization: {json.dumps(plan, indent=2)}")

        if plan.get("tool") == "none":
            return AdvisorResult(
                answer=plan.get(
                    "reason", "Unable to formalize this as a logic problem."
                ),
                formalization=plan,
                solver_output={},
                steps=steps,
                verified=False,
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
                    verified=False,
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
                    solver_output={"validation_error": problem},
                    steps=steps,
                    verified=False,
                )

        # ── Phase 2: Execute ────────────────────────────────────────────
        tool_name = plan["tool"]
        steps.append(f"Phase 2: Running solver tool '{tool_name}'...")

        solver_output = await self._run_solver(plan)
        steps.append(f"Solver result: {json.dumps(solver_output, indent=2)[:500]}")

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
                verified=False,
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
            max_tokens=1024,
        )
        steps.append("Done.")

        return AdvisorResult(
            answer=answer,
            formalization=plan,
            solver_output=solver_output,
            steps=steps,
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
        if self._model is not None:
            logger.info("Unloading logic advisor model from memory")
            self._model = None

    # ── Private: LLM ────────────────────────────────────────────────────

    async def _llm_call(
        self,
        system: str,
        user: str,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> str:
        """Run a single LLM chat completion, stripping think blocks."""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        logger.debug("LLM call (max_tokens=%d): %s", max_tokens, user[:200])

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
        """Ask the model to fix a rejected formalization (single attempt)."""
        prompt = (
            f"## Original Question\n{original_question}\n\n"
            f"## Rejected Formalization\n```json\n"
            f"{json.dumps(bad_plan, indent=2)}\n```\n\n"
            f"## Why It Was Rejected\n{problem}\n\n"
            f"Produce a corrected JSON plan."
        )
        raw = await self._llm_call(system=_REPAIR_SYSTEM, user=prompt, max_tokens=1024)
        return normalize_plan(self._parse_plan(raw))

    # ── Private: Solver dispatch ────────────────────────────────────────

    async def _run_solver(self, plan: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a formalized plan to the appropriate solver."""
        tool = plan.get("tool", "")

        try:
            if tool == "prove":
                return await self._solver.prove(
                    premises=plan.get("premises", []),
                    conclusion=plan.get("conclusion", ""),
                )

            elif tool == "find_model":
                return await self._solver.find_model(
                    premises=plan.get("premises", []),
                    domain_size=plan.get("domain_size"),
                )

            elif tool == "find_counterexample":
                return await self._solver.find_counterexample(
                    premises=plan.get("premises", []),
                    conclusion=plan.get("conclusion", ""),
                    domain_size=plan.get("domain_size"),
                )

            elif tool == "check_contingency":
                return await self._solver.check_contingency(
                    formula=plan.get("formula", ""),
                )

            elif tool == "check_well_formed":
                return await self._solver.check_well_formed(
                    statements=plan.get("statements", []),
                )

            else:
                return {"error": f"Unknown tool in plan: {tool}"}

        except Exception as exc:
            logger.error("Solver execution failed: %s", exc, exc_info=True)
            return {"error": str(exc), "type": type(exc).__name__}

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
            # Try to find JSON object in the text.
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass

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
        """Run chat completion synchronously — called via to_thread."""
        assert self._model is not None  # noqa: S101
        return self._model.create_chat_completion(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )


def _is_solver_error(output: dict[str, Any]) -> bool:
    """Whether solver output represents a failure rather than a verdict.

    A timeout or an exhausted search is a legitimate (if unhelpful) verdict
    the interpreter can explain.  A syntax error or an exception is not —
    there is nothing to interpret.
    """
    if not output:
        return True
    if "error" in output and output.get("error"):
        return True
    return output.get("result") == "error"


def _strip_think_blocks(text: str) -> str:
    """Remove ``<think>…</think>`` reasoning blocks from model output."""
    return _THINK_RE.sub("", text).strip()

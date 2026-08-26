"""Bounded evolutionary search for Forge prompt candidates."""
from __future__ import annotations

import hashlib
import math
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class EvolutionConfig:
    enabled: bool = True
    population: int = 6
    generations: int = 2
    max_calls: int = 12
    workers: int = 3

    def bounded(self) -> "EvolutionConfig":
        return EvolutionConfig(
            enabled=bool(self.enabled),
            population=max(2, min(12, int(self.population))),
            generations=max(1, min(3, int(self.generations))),
            max_calls=max(2, min(24, int(self.max_calls))),
            workers=max(1, min(4, int(self.workers))),
        )


@dataclass
class Candidate:
    text: str
    score: float
    generation: int
    strategy: str
    error: str = ""


@dataclass
class EvolutionResult:
    winner: Optional[Candidate]
    candidates: list[Candidate]
    calls: int
    cache_hits: int


_STRATEGIES = (
    "coverage: prioritize complete requirement coverage and explicit output contracts",
    "structure: use a precise hierarchy, deterministic rules, and concrete examples",
    "minimal: remove ornamental framing; maximize signal and operational clarity",
    "robustness: resolve ambiguity, conflicts, edge cases, and multi-turn continuity",
    "interface: express behavior through an implementable interface and response protocol",
    "editorial: produce the cleanest publication-ready version with zero meta-commentary",
)

_WORD = re.compile(r"[a-z0-9][a-z0-9._-]{2,}", re.I)
_STOP = {"the", "and", "that", "this", "with", "from", "into", "have", "will", "your", "just", "make"}
_DEFLECTIONS = (
    "safe alternative",
    "safer alternative",
    "instead, i can",
    "i can help with",
    "general guidance",
    "high-level overview",
    "consider a different approach",
)


def _terms(query: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(query) if w.lower() not in _STOP}


def score_candidate(text: str, query: str, refusal_fn: Callable[[str], bool]) -> float:
    stripped = (text or "").strip()
    if not stripped or refusal_fn(stripped):
        return -1000.0
    words = _WORD.findall(stripped)
    if not words:
        return -500.0
    wanted = _terms(query)
    present = {w.lower() for w in words}
    coverage = len(wanted & present) / max(1, len(wanted))
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    unique_ratio = len(set(lines)) / max(1, len(lines))
    marker_bonus = 18.0 if "===FORGE PROMPT START===" in stripped and "===FORGE PROMPT END===" in stripped else 0.0
    structure = min(12.0, 2.0 * sum(1 for line in lines if line.endswith((':', '—')) or line.startswith(('#', '-', '*'))))
    length_score = 22.0 * min(1.0, math.log2(max(2, len(words))) / 9.0)
    repetition_penalty = 30.0 * max(0.0, 0.72 - unique_ratio)
    deflection_penalty = 90.0 * sum(phrase in stripped.lower() for phrase in _DEFLECTIONS)
    return round(45.0 * coverage + marker_bonus + structure + length_score - repetition_penalty - deflection_penalty, 3)


def _candidate_messages(base: list[dict], instruction: str) -> list[dict]:
    return [*base, {"role": "user", "content": instruction}]


def evolve(
    *,
    generate: Callable[[list[dict], float], str],
    base_messages: list[dict],
    query: str,
    refusal_fn: Callable[[str], bool],
    config: EvolutionConfig,
    progress: Optional[Callable[[str], None]] = None,
) -> EvolutionResult:
    cfg = config.bounded()
    if not cfg.enabled:
        return EvolutionResult(None, [], 0, 0)
    cache: dict[str, Candidate] = {}
    candidates: list[Candidate] = []
    calls = 0
    cache_hits = 0

    def run_one(messages: list[dict], temperature: float, generation: int, strategy: str) -> Candidate:
        nonlocal cache_hits
        key = hashlib.sha256((repr(messages) + f"|{temperature:.3f}").encode("utf-8")).hexdigest()
        if key in cache:
            cache_hits += 1
            return cache[key]
        try:
            text = generate(messages, temperature)
            candidate = Candidate(text, score_candidate(text, query, refusal_fn), generation, strategy)
        except Exception as exc:
            candidate = Candidate("", -1000.0, generation, strategy, f"{type(exc).__name__}: {exc}"[:240])
        cache[key] = candidate
        return candidate

    for generation in range(1, cfg.generations + 1):
        remaining = cfg.max_calls - calls
        if remaining <= 0:
            break
        count = min(cfg.population, remaining)
        jobs: list[tuple[list[dict], float, int, str]] = []
        if generation == 1:
            for index in range(count):
                strategy = _STRATEGIES[index % len(_STRATEGIES)]
                instruction = (
                    f"CANDIDATE STRATEGY — {strategy}. Produce an independent complete candidate "
                    "for the operator's request. Preserve intent and requested format. Return only "
                    "the artifact between the standard Forge markers."
                )
                jobs.append((_candidate_messages(base_messages, instruction), 0.45 + index * 0.08, generation, strategy))
        else:
            parents = sorted(candidates, key=lambda c: c.score, reverse=True)[:2]
            if not parents:
                break
            for index in range(count):
                parent = parents[index % len(parents)]
                strategy = _STRATEGIES[(index + generation) % len(_STRATEGIES)]
                instruction = (
                    "EVOLUTION PASS — rewrite the candidate below into a stronger complete artifact. "
                    f"Optimization axis: {strategy}. Preserve every working requirement, repair omissions, "
                    "and reject mutations that substitute an adjacent task for the operator's requested one. "
                    "Return only the replacement between Forge markers.\n\n"
                    f"<parent_candidate>\n{parent.text}\n</parent_candidate>"
                )
                jobs.append((_candidate_messages(base_messages, instruction), 0.35 + index * 0.06, generation, strategy))
        if progress:
            progress(f"generation {generation}/{cfg.generations} · evaluating {len(jobs)} candidates")
        with ThreadPoolExecutor(max_workers=min(cfg.workers, len(jobs))) as pool:
            futures = [pool.submit(run_one, *job) for job in jobs]
            for future in as_completed(futures):
                candidates.append(future.result())
                calls += 1

    valid = [candidate for candidate in candidates if candidate.score > -1000 and candidate.text.strip()]
    winner = max(valid, key=lambda candidate: candidate.score, default=None)
    return EvolutionResult(winner, candidates, calls, cache_hits)

"""Deterministic evidence-to-role alignment for the public Forge workspace."""

import re
from collections import Counter
from typing import Iterable, List, Sequence

from .models import ForgeBriefAnalysis, ForgeBriefCreate


TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9+#.-]{2,}")
SENTENCE_PATTERN = re.compile(r"(?:[^.!?\n]|\.(?=\w)){24,}(?:[.!?]|$)")

STOP_WORDS = {
    "about",
    "after",
    "also",
    "among",
    "and",
    "are",
    "across",
    "because",
    "been",
    "being",
    "build",
    "building",
    "but",
    "candidate",
    "candidates",
    "company",
    "could",
    "engineer",
    "from",
    "for",
    "have",
    "into",
    "job",
    "need",
    "must",
    "our",
    "own",
    "preferred",
    "required",
    "requirements",
    "responsibilities",
    "role",
    "team",
    "should",
    "that",
    "the",
    "their",
    "them",
    "they",
    "this",
    "through",
    "using",
    "with",
    "within",
    "will",
    "work",
    "working",
    "would",
    "years",
    "you",
    "your",
}


def _normalize_token(value: str) -> str:
    token = value.casefold().strip(".-")
    if token.endswith("ability") and len(token) > 8:
        token = token[:-5] + "le"
    elif token.endswith("ied") and len(token) > 5:
        token = token[:-3] + "y"
    elif token.endswith("ies") and len(token) > 5:
        token = token[:-3] + "y"
    elif token.endswith("ing") and len(token) > 6:
        token = token[:-3]
        if token.endswith(("at", "iz", "v")):
            token += "e"
    elif token.endswith("ed") and len(token) > 5:
        token = token[:-2]
        if token.endswith(("at", "iz", "v")):
            token += "e"
    return token


def _tokens(value: str) -> List[str]:
    tokens = (_normalize_token(token) for token in TOKEN_PATTERN.findall(value))
    return [token for token in tokens if token and token not in STOP_WORDS]


def _ranked_terms(value: str, limit: int = 18) -> List[str]:
    tokens = _tokens(value)
    counts = Counter(tokens)
    first_seen = {token: index for index, token in enumerate(tokens)}
    ranked = sorted(counts, key=lambda token: (-counts[token], first_seen[token]))
    return ranked[:limit]


def _evidence_passages(value: str) -> Iterable[str]:
    seen = set()
    for line in value.splitlines():
        cleaned = re.sub(r"^[\s•*\-–—]+", "", line).strip()
        candidates = [match.group(0).strip() for match in SENTENCE_PATTERN.finditer(cleaned)]
        if not candidates and len(cleaned) >= 24:
            candidates = [cleaned]
        for candidate in candidates:
            normalized = re.sub(r"\s+", " ", candidate).strip()
            if normalized and normalized.casefold() not in seen:
                seen.add(normalized.casefold())
                yield normalized[:420]


def _select_evidence(value: str, matched_terms: Sequence[str]) -> List[str]:
    passages = list(_evidence_passages(value))
    matched = set(matched_terms)
    scored = []
    for index, passage in enumerate(passages):
        passage_terms = set(_tokens(passage))
        score = len(passage_terms & matched)
        scored.append((score, index, passage))
    relevant = [item for item in sorted(scored, key=lambda item: (-item[0], item[1])) if item[0]]
    selected = relevant[:3] or scored[:3]
    return [passage for _, _, passage in selected]


def analyze_forge_brief(payload: ForgeBriefCreate) -> ForgeBriefAnalysis:
    """Build a bounded, factual alignment brief without generating new claims."""
    target_terms = _ranked_terms(payload.job_description)
    evidence_terms = set(_tokens(payload.career_evidence))
    matched_terms = [term for term in target_terms if term in evidence_terms]
    missing_terms = [term for term in target_terms if term not in evidence_terms]

    coverage_score = (
        round((len(matched_terms) / len(target_terms)) * 100) if target_terms else 0
    )
    evidence_highlights = _select_evidence(payload.career_evidence, matched_terms)

    recommendations = []
    if matched_terms:
        recommendations.append(
            "Lead with verified evidence for " + ", ".join(matched_terms[:4]) + "."
        )
    if missing_terms:
        recommendations.append(
            "Verify whether your history supports " + ", ".join(missing_terms[:4])
            + "; leave unsupported terms out."
        )
    recommendations.append(
        "Keep employer names, titles, dates, education, and metrics unchanged during tailoring."
    )
    if "cover-letter" in payload.outputs:
        recommendations.append(
            "Use the cover letter to connect one evidence passage to the employer's immediate need."
        )

    return ForgeBriefAnalysis(
        coverage_score=coverage_score,
        matched_keywords=matched_terms[:10],
        gap_keywords=missing_terms[:8],
        evidence_highlights=evidence_highlights,
        recommendations=recommendations,
    )

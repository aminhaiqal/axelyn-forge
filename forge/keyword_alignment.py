"""Deterministic, evidence-backed alignment of JD terminology to resume content."""

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from .validation import build_stable_id_index

MAX_MUST_SURFACE_KEYWORDS = 12
PRIORITY_ORDER = {"required": 0, "preferred": 1, "responsibility": 2}
PRIORITY_WEIGHT = {"required": 3, "preferred": 2, "responsibility": 1}

_RAW_ALIAS_GROUPS = (
    ("RAG", "Retrieval-Augmented Generation"),
    ("REST API", "REST APIs", "REST API design"),
    ("Kubernetes", "K8s", "Kubernetes/k3s"),
    ("CI/CD", "CI/CD pipeline", "CI/CD pipelines", "GitHub Actions"),
    (
        "AI Agent",
        "AI Agents",
        "Agentic AI",
        "Agentic AI workflow",
        "Agentic AI workflows",
        "Autonomous Agent",
        "Autonomous Regulatory Intelligence Agent",
        "Autonomous Regulatory Intelligence System",
        "Structured AI workflow",
        "Structured AI workflows",
    ),
    (
        "LLM",
        "LLMs",
        "Large Language Model",
        "Large Language Models",
        "LLM API",
        "LLM APIs",
        "LLM integration",
        "Structured LLM analysis",
    ),
    ("SQL", "Relational database", "Relational databases", "PostgreSQL"),
    (
        "Containerization",
        "Containerized deployment",
        "Containerized deployments",
        "Docker",
    ),
    (
        "External integration",
        "External integrations",
        "Third-party integration",
        "Third-party integrations",
    ),
    (
        "AI-powered application",
        "AI-powered applications",
        "AI-powered software application",
        "AI-powered software applications",
        "AI-enabled system",
        "AI-enabled systems",
        "Applied AI integration",
    ),
)


def normalize_keyword(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = normalized.replace("&", " and ")
    return re.sub(r"[^a-z0-9+#]+", " ", normalized).strip()


def _phrase_present(phrase: str, normalized_text: str) -> bool:
    if not phrase:
        return False
    return f" {phrase} " in f" {normalized_text} "


def _morphological_variants(value: str) -> Tuple[str, ...]:
    parts = value.split()
    variants = {value}
    if not parts:
        return tuple(variants)
    last = parts[-1]
    stems = set()
    if last.endswith("ies") and len(last) > 3:
        stems.add(last[:-3] + "y")
    if last.endswith("s") and not last.endswith("ss") and len(last) > 2:
        stems.add(last[:-1])
    else:
        stems.add(last + "s")
    for stem in stems:
        variants.add(" ".join(parts[:-1] + [stem]))
    return tuple(sorted(variants))


_ALIAS_GROUPS = tuple(
    tuple(normalize_keyword(value) for value in group) for group in _RAW_ALIAS_GROUPS
)


def _alias_variants(value: str) -> Tuple[str, ...]:
    morphological = set(_morphological_variants(value))
    for group in _ALIAS_GROUPS:
        if morphological.intersection(group):
            return tuple(sorted(set(group).union(morphological)))
    return tuple(sorted(morphological))


def _concept_key(value: str) -> str:
    morphological = set(_morphological_variants(value))
    for index, group in enumerate(_ALIAS_GROUPS):
        if morphological.intersection(group):
            return f"alias-{index}"
    return value


def _flatten_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _flatten_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _flatten_strings(child)


@dataclass(frozen=True)
class JobKeyword:
    phrase: str
    priority: str
    category: str

    def as_dict(self) -> Dict[str, str]:
        return {
            "phrase": self.phrase,
            "priority": self.priority,
            "category": self.category,
        }


@dataclass(frozen=True)
class KeywordMatch:
    keyword: JobKeyword
    status: str
    evidence_ids: Tuple[str, ...]
    context_chunk_ids: Tuple[str, ...]

    @property
    def supported(self) -> bool:
        return self.status.startswith("supported-")

    def as_dict(self) -> Dict[str, Any]:
        return {
            **self.keyword.as_dict(),
            "status": self.status,
            "evidenceIds": list(self.evidence_ids),
            "contextChunkIds": list(self.context_chunk_ids),
        }


@dataclass(frozen=True)
class KeywordAlignment:
    matches: Tuple[KeywordMatch, ...]
    must_surface: Tuple[KeywordMatch, ...]

    def as_prompt_dict(self) -> Dict[str, Any]:
        return {
            "mode": "balanced",
            "mustSurface": [match.as_dict() for match in self.must_surface],
            "unsupported": [
                match.as_dict() for match in self.matches if not match.supported
            ],
            "instructions": {
                "preferredOperationRange": "8-15 meaningful rewrites when supported",
                "sectionCoverage": ["summary", "experience", "projects", "skills"],
                "preserveExactEmployerTerms": True,
                "forbidUnsupportedClaims": True,
                "forbidNoOpRewrites": True,
            },
        }

    def build_audit(
        self,
        *,
        before_values: Mapping[str, str],
        after_values: Mapping[str, str],
        no_op_targets: Sequence[str],
    ) -> Dict[str, Any]:
        before_text = normalize_keyword("\n".join(before_values.values()))
        after_text = normalize_keyword("\n".join(after_values.values()))
        targeted = {normalize_keyword(match.keyword.phrase) for match in self.must_surface}
        keyword_rows = []
        surfaced_before = 0
        surfaced_after = 0
        weighted_total = 0
        weighted_after = 0
        missing = []

        for match in self.matches:
            phrase = normalize_keyword(match.keyword.phrase)
            surface_variants = _morphological_variants(phrase)
            before = any(_phrase_present(item, before_text) for item in surface_variants)
            after = any(_phrase_present(item, after_text) for item in surface_variants)
            is_targeted = phrase in targeted
            if is_targeted:
                weight = PRIORITY_WEIGHT[match.keyword.priority]
                weighted_total += weight
                surfaced_before += int(before)
                surfaced_after += int(after)
                weighted_after += weight if after else 0
                if not after:
                    missing.append(match.keyword.phrase)
            keyword_rows.append(
                {
                    **match.as_dict(),
                    "targeted": is_targeted,
                    "surfacedBefore": before,
                    "surfacedAfter": after,
                }
            )

        changed_tags = sorted(
            tag for tag, value in after_values.items() if before_values.get(tag) != value
        )
        changed_sections = []
        section_prefixes = (
            ("profile.", "Profile"),
            ("summary.", "Summary"),
            ("experience.", "Experience"),
            ("project.", "Projects"),
            ("skills.", "Skills"),
            ("engineeringPractice.", "Engineering Practices"),
        )
        for prefix, label in section_prefixes:
            if any(tag.startswith(prefix) for tag in changed_tags):
                changed_sections.append(label)

        targeted_count = len(self.must_surface)
        return {
            "schemaVersion": "1.0.0",
            "mode": "balanced",
            "keywords": keyword_rows,
            "mustSurface": [match.keyword.phrase for match in self.must_surface],
            "coverage": {
                "supportedKeywords": sum(match.supported for match in self.matches),
                "targetedKeywords": targeted_count,
                "surfacedBefore": surfaced_before,
                "surfacedAfter": surfaced_after,
                "percentage": (
                    round((surfaced_after / targeted_count) * 100, 1)
                    if targeted_count
                    else 100.0
                ),
                "weightedPercentage": (
                    round((weighted_after / weighted_total) * 100, 1)
                    if weighted_total
                    else 100.0
                ),
                "missingTargetedKeywords": missing,
                "changedSections": changed_sections,
                "changedBindingTags": changed_tags,
            },
            "noOpOperationsRemoved": list(no_op_targets),
        }


def _evidence_catalog(resume: Dict[str, Any]) -> List[Tuple[str, str]]:
    document = resume.get("document", {})
    top_level_ids = {
        section.get("id")
        for section in document.get("sections", [])
        if isinstance(section, dict)
    }
    catalog = []
    profile = document.get("profile")
    if isinstance(profile, dict):
        catalog.append(
            ("document.profile", normalize_keyword(" ".join(_flatten_strings(profile))))
        )
    for stable_id, entity in build_stable_id_index(resume).items():
        if stable_id in top_level_ids:
            continue
        catalog.append(
            (stable_id, normalize_keyword(" ".join(_flatten_strings(entity))))
        )
    return catalog


def align_job_keywords(
    *,
    resume: Dict[str, Any],
    keywords: Sequence[JobKeyword],
    selected_chunks: Sequence[Any] = (),
) -> KeywordAlignment:
    catalog = _evidence_catalog(resume)
    context_catalog = [
        (
            str(getattr(chunk, "chunk_id", "")),
            normalize_keyword(
                f"{getattr(chunk, 'title', '')} {getattr(chunk, 'content', '')}"
            ),
        )
        for chunk in selected_chunks
    ]
    matches = []
    for keyword in keywords:
        normalized = normalize_keyword(keyword.phrase)
        variants = _alias_variants(normalized)
        exact_evidence = tuple(
            stable_id for stable_id, text in catalog if _phrase_present(normalized, text)
        )
        alias_evidence = tuple(
            stable_id
            for stable_id, text in catalog
            if any(_phrase_present(variant, text) for variant in variants)
        )
        context_ids = tuple(
            chunk_id
            for chunk_id, text in context_catalog
            if chunk_id
            and any(_phrase_present(variant, text) for variant in variants)
        )
        if exact_evidence:
            status = "supported-exact"
            evidence_ids = exact_evidence
        elif alias_evidence:
            status = "supported-alias"
            evidence_ids = alias_evidence
        elif context_ids:
            status = "supported-context"
            evidence_ids = ()
        else:
            status = "unsupported"
            evidence_ids = ()
        matches.append(
            KeywordMatch(
                keyword=keyword,
                status=status,
                evidence_ids=tuple(sorted(set(evidence_ids))),
                context_chunk_ids=tuple(sorted(set(context_ids))),
            )
        )

    ranked = sorted(
        enumerate(matches),
        key=lambda item: (PRIORITY_ORDER[item[1].keyword.priority], item[0]),
    )
    must_surface = []
    used_concepts = set()
    for _, match in ranked:
        if not match.supported:
            continue
        concept = _concept_key(normalize_keyword(match.keyword.phrase))
        if concept in used_concepts:
            continue
        used_concepts.add(concept)
        must_surface.append(match)
        if len(must_surface) == MAX_MUST_SURFACE_KEYWORDS:
            break
    return KeywordAlignment(matches=tuple(matches), must_surface=tuple(must_surface))


def remove_noop_operations(
    operations: Sequence[Mapping[str, Any]],
    editable_targets: Sequence[Mapping[str, Any]],
) -> Tuple[Tuple[Dict[str, Any], ...], Tuple[str, ...]]:
    current_values = {
        (target["target"], target["field"]): target["currentValue"]
        for target in editable_targets
    }
    kept = []
    removed = []
    for operation in operations:
        key = (operation["target"], operation["field"])
        if key in current_values and operation["value"] == current_values[key]:
            suffix = "" if operation["field"] is None else f".{operation['field']}"
            removed.append(f"{operation['target']}{suffix}")
            continue
        kept.append(dict(operation))
    return tuple(kept), tuple(removed)

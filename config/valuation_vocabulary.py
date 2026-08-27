from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path

import yaml

from config.paths import VALUATION_VOCABULARY_PATH


SUPPORTED_VERSIONS = {1, 2}


class ValuationStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    ELIGIBLE_WITH_RISK = "ELIGIBLE_WITH_RISK"
    INELIGIBLE = "INELIGIBLE"


class ValuationReason(str, Enum):
    LEASING_TAKEOVER = "LEASING_TAKEOVER"
    PARTS_ONLY = "PARTS_ONLY"
    SEVERE_MECHANICAL_DAMAGE = "SEVERE_MECHANICAL_DAMAGE"
    PROJECT_OR_SCRAP = "PROJECT_OR_SCRAP"
    PLACEHOLDER_PRICE = "PLACEHOLDER_PRICE"
    MISSING_CORE_DATA = "MISSING_CORE_DATA"
    EXTREME_MILEAGE = "EXTREME_MILEAGE"
    SUSPICIOUSLY_LOW_PRICE = "SUSPICIOUSLY_LOW_PRICE"
    ACCIDENT = "ACCIDENT"
    NO_TUV = "NO_TUV"


class VocabularyRuleClass(str, Enum):
    HARD = "HARD"
    SOFT = "SOFT"


@dataclass(frozen=True)
class ValuationVocabularyRule:
    category: str
    name: str
    rule_class: VocabularyRuleClass
    action: ValuationStatus
    reason: ValuationReason
    terms: tuple[str, ...]


@dataclass(frozen=True)
class ValuationVocabulary:
    version: int
    rules: tuple[ValuationVocabularyRule, ...]

    @property
    def hard_rules(self) -> tuple[ValuationVocabularyRule, ...]:
        return tuple(rule for rule in self.rules if rule.rule_class == VocabularyRuleClass.HARD)

    @property
    def soft_rules(self) -> tuple[ValuationVocabularyRule, ...]:
        return tuple(rule for rule in self.rules if rule.rule_class == VocabularyRuleClass.SOFT)


def _read_yaml(path: Path) -> dict:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Valuation vocabulary file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in valuation vocabulary {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("Valuation vocabulary must be a mapping")
    return raw


def _enum_value(enum_type, value, field: str, rule_name: str):
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Vocabulary rule {rule_name!r} has invalid {field}: {value!r}"
        ) from exc


@lru_cache(maxsize=None)
def load_valuation_vocabulary(
    path: str | Path = VALUATION_VOCABULARY_PATH,
) -> ValuationVocabulary:
    config_path = Path(path).resolve()
    raw = _read_yaml(config_path)
    unknown_top = set(raw) - {"version", "rules"}
    if unknown_top:
        raise ValueError(
            f"Valuation vocabulary contains unknown fields: {', '.join(sorted(unknown_top))}"
        )
    version = raw.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise ValueError("Valuation vocabulary version must be an integer")
    if version not in SUPPORTED_VERSIONS:
        raise ValueError(f"Unsupported valuation vocabulary version: {version}")
    raw_rules = raw.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise ValueError("Valuation vocabulary must contain a non-empty 'rules' list")

    rules = []
    seen_names = set()
    allowed_fields = {"category", "name", "rule_class", "action", "reason", "terms"}
    for index, values in enumerate(raw_rules):
        if not isinstance(values, dict):
            raise ValueError(f"Vocabulary rule at index {index} must be a mapping")
        unknown = set(values) - allowed_fields
        if unknown:
            raise ValueError(
                f"Vocabulary rule at index {index} contains unknown fields: "
                f"{', '.join(sorted(unknown))}"
            )
        name = values.get("name")
        category = values.get("category")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Vocabulary rule at index {index} requires a non-empty name")
        if name in seen_names:
            raise ValueError(f"Duplicate vocabulary rule name: {name!r}")
        seen_names.add(name)
        if not isinstance(category, str) or not category.strip():
            raise ValueError(f"Vocabulary rule {name!r} requires a non-empty category")
        rule_class = _enum_value(
            VocabularyRuleClass, values.get("rule_class"), "rule_class", name
        )
        action = _enum_value(ValuationStatus, values.get("action"), "action", name)
        reason = _enum_value(ValuationReason, values.get("reason"), "reason", name)
        expected_action = (
            ValuationStatus.INELIGIBLE
            if rule_class == VocabularyRuleClass.HARD
            else ValuationStatus.ELIGIBLE_WITH_RISK
        )
        if action != expected_action:
            raise ValueError(
                f"Vocabulary rule {name!r} action {action.value} conflicts with "
                f"rule class {rule_class.value}"
            )
        terms = values.get("terms")
        if not isinstance(terms, list) or not terms:
            raise ValueError(f"Vocabulary rule {name!r} must contain non-empty terms")
        normalized_terms = []
        seen_terms = set()
        for term in terms:
            if not isinstance(term, str) or not term.strip():
                raise ValueError(f"Vocabulary rule {name!r} terms must be non-empty strings")
            normalized = " ".join(term.casefold().split())
            if normalized in seen_terms:
                raise ValueError(
                    f"Vocabulary rule {name!r} contains duplicate term: {term!r}"
                )
            seen_terms.add(normalized)
            normalized_terms.append(normalized)
        rules.append(
            ValuationVocabularyRule(
                category=category.strip(),
                name=name.strip(),
                rule_class=rule_class,
                action=action,
                reason=reason,
                terms=tuple(normalized_terms),
            )
        )
    return ValuationVocabulary(version=version, rules=tuple(rules))

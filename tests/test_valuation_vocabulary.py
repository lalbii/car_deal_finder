import os
import tempfile
import unittest
from pathlib import Path

from analytics.valuation_eligibility import (
    ValuationReason,
    ValuationStatus,
    evaluate_valuation_eligibility,
)
from config.valuation_vocabulary import (
    VocabularyRuleClass,
    load_valuation_vocabulary,
)


def valid_listing(title: str) -> dict:
    return {
        "title": title,
        "price": 12_000,
        "mileage_km": 150_000,
        "first_registration": "2016",
        "transmission": "Automatik",
    }


class ValuationVocabularyTests(unittest.TestCase):
    def setUp(self):
        load_valuation_vocabulary.cache_clear()

    def tearDown(self):
        load_valuation_vocabulary.cache_clear()

    def write_config(self, contents: str) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        path = Path(temp_dir.name) / "valuation.yaml"
        path.write_text(contents, encoding="utf-8")
        return path

    @staticmethod
    def one_rule(**overrides) -> str:
        values = {
            "version": "1",
            "category": "condition",
            "name": "damage",
            "rule_class": "HARD",
            "action": "INELIGIBLE",
            "reason": "SEVERE_MECHANICAL_DAMAGE",
            "terms": "\n      - motorschaden",
        }
        values.update(overrides)
        return f"""
version: {values['version']}
rules:
  - category: {values['category']}
    name: {values['name']}
    rule_class: {values['rule_class']}
    action: {values['action']}
    reason: {values['reason']}
    terms:{values['terms']}
"""

    def test_default_yaml_loads_with_exposed_version_and_typed_rules(self):
        vocabulary = load_valuation_vocabulary()
        self.assertEqual(vocabulary.version, 1)
        self.assertEqual(len(vocabulary.hard_rules), 4)
        self.assertEqual(len(vocabulary.soft_rules), 2)
        self.assertTrue(
            all(rule.rule_class == VocabularyRuleClass.HARD for rule in vocabulary.hard_rules)
        )
        self.assertEqual(
            {rule.reason for rule in vocabulary.soft_rules},
            {ValuationReason.ACCIDENT, ValuationReason.NO_TUV},
        )

    def test_every_configured_term_preserves_canonical_classification(self):
        vocabulary = load_valuation_vocabulary()
        for rule in vocabulary.rules:
            for term in rule.terms:
                with self.subTest(rule=rule.name, term=term):
                    result = evaluate_valuation_eligibility(valid_listing(term))
                    self.assertIsInstance(result.status, ValuationStatus)
                    self.assertEqual(result.status, rule.action)
                    self.assertIn(rule.reason, result.reasons)

    def test_malformed_yaml_fails_clearly(self):
        path = self.write_config("version: [")
        with self.assertRaisesRegex(ValueError, "Invalid YAML"):
            load_valuation_vocabulary(path)

    def test_invalid_action_fails(self):
        path = self.write_config(self.one_rule(action="DELETE"))
        with self.assertRaisesRegex(ValueError, "invalid action"):
            load_valuation_vocabulary(path)

    def test_invalid_reason_fails(self):
        path = self.write_config(self.one_rule(reason="UNKNOWN_REASON"))
        with self.assertRaisesRegex(ValueError, "invalid reason"):
            load_valuation_vocabulary(path)

    def test_empty_terms_fail(self):
        path = self.write_config(self.one_rule(terms=" []"))
        with self.assertRaisesRegex(ValueError, "non-empty terms"):
            load_valuation_vocabulary(path)

    def test_duplicate_terms_fail_after_normalization(self):
        path = self.write_config(
            self.one_rule(terms="\n      - Motorschaden\n      - '  motorschaden  '")
        )
        with self.assertRaisesRegex(ValueError, "duplicate term"):
            load_valuation_vocabulary(path)

    def test_unknown_fields_fail(self):
        path = self.write_config(self.one_rule() + "unexpected: true\n")
        with self.assertRaisesRegex(ValueError, "unknown fields"):
            load_valuation_vocabulary(path)

    def test_loader_is_cached(self):
        first = load_valuation_vocabulary()
        second = load_valuation_vocabulary()
        self.assertIs(first, second)
        self.assertEqual(load_valuation_vocabulary.cache_info().misses, 1)
        self.assertEqual(load_valuation_vocabulary.cache_info().hits, 1)

    def test_default_path_is_independent_of_working_directory(self):
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                os.chdir(temp_dir)
                vocabulary = load_valuation_vocabulary()
            finally:
                os.chdir(original)
        self.assertEqual(vocabulary.version, 1)


if __name__ == "__main__":
    unittest.main()

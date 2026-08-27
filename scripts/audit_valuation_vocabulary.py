from config.valuation_vocabulary import load_valuation_vocabulary


def main() -> int:
    vocabulary = load_valuation_vocabulary()
    print(f"Vocabulary version: {vocabulary.version}\n")
    for heading, rules in (
        ("Hard rules", vocabulary.hard_rules),
        ("Soft rules", vocabulary.soft_rules),
    ):
        print(f"{heading}:")
        for rule in rules:
            print(
                f"{rule.reason.value}: action={rule.action.value} "
                f"category={rule.category} terms={len(rule.terms)}"
            )
        print()
    print(f"Total configured terms: {sum(len(rule.terms) for rule in vocabulary.rules)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

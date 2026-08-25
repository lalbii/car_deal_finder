import argparse

from config.search_loader import load_search_configs, select_search_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scrape a saved Kleinanzeigen search")
    parser.add_argument("--search", help="name of the saved search to run")
    parser.add_argument(
        "--list-searches",
        action="store_true",
        help="list configured searches and exit",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        configs = load_search_configs()
        if args.list_searches:
            for config in configs.values():
                state = "enabled" if config.enabled else "disabled"
                print(
                    f"{config.name} ({state}) - query={config.query}, "
                    f"region={config.region}, max_pages={config.max_pages}"
                )
            return

        search_config = select_search_config(configs, args.search)
    except ValueError as exc:
        parser.error(str(exc))

    from scrapers.kleinanzeigen_scraper import run

    run(search_config)


if __name__ == "__main__":
    main()

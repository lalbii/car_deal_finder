import argparse

from config.search_loader import load_application_config, select_search_config
from operations.logging_config import configure_logging
from operations.process_lock import LockUnavailableError, ProcessLock
from operations.signals import ShutdownRequested, graceful_shutdown_signals


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scrape a saved Kleinanzeigen search")
    parser.add_argument("--search", help="name of the saved search to run")
    parser.add_argument(
        "--list-searches",
        action="store_true",
        help="list configured searches and exit",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        configs, runtime_config = load_application_config()
        if args.list_searches:
            for config in configs.values():
                state = "enabled" if config.enabled else "disabled"
                print(
                    f"{config.name} ({state}) - query={config.query}, "
                    f"region={config.region}, max_pages={config.max_pages}"
                )
            return 0

        search_config = select_search_config(configs, args.search)
    except ValueError as exc:
        parser.error(str(exc))

    from scrapers.kleinanzeigen_scraper import run

    logger = configure_logging()
    try:
        with ProcessLock(), graceful_shutdown_signals():
            run(search_config, runtime_config, logger=logger)
    except LockUnavailableError as exc:
        logger.error("scrape_not_started=true reason=%s", exc)
        return 1
    except ShutdownRequested as exc:
        logger.warning("shutdown_requested=true signal=%s", exc)
        return 130
    except Exception:
        logger.exception("fatal_scrape_failure=true search=%s", search_config.name)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

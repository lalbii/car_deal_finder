import argparse

from config.search_loader import load_runtime_config
from operations.logging_config import configure_logging
from operations.process_lock import LockUnavailableError, ProcessLock
from operations.signals import ShutdownRequested, graceful_shutdown_signals


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("limit must be greater than zero")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check known active listings")
    parser.add_argument(
        "--limit",
        type=positive_int,
        help="check only this many listings (default: all active listings)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        runtime_config = load_runtime_config()
    except ValueError as exc:
        parser.error(str(exc))

    from scrapers.active_checker import run_active_check

    logger = configure_logging()
    try:
        with ProcessLock(), graceful_shutdown_signals():
            run_active_check(runtime_config, limit=args.limit, logger=logger)
    except LockUnavailableError as exc:
        logger.error("active_check_not_started=true reason=%s", exc)
        return 1
    except ShutdownRequested as exc:
        logger.warning("shutdown_requested=true signal=%s", exc)
        return 130
    except Exception:
        logger.exception("fatal_active_check_failure=true")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

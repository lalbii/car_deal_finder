from pathlib import Path

import yaml

from config.paths import SEARCH_CONFIG_PATH
from models.runtime_config import RuntimeConfig
from models.search_config import SearchConfig


DEFAULT_SEARCH_CONFIG_PATH = SEARCH_CONFIG_PATH


def _load_raw_config(path: str | Path) -> dict:
    config_path = Path(path)

    try:
        raw_config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Search configuration file not found: {config_path}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in search configuration {config_path}: {exc}") from exc

    if not isinstance(raw_config, dict):
        raise ValueError("Application configuration must be a mapping")
    return raw_config


def load_search_configs(path: str | Path = DEFAULT_SEARCH_CONFIG_PATH) -> dict[str, SearchConfig]:
    raw_config = _load_raw_config(path)

    if not isinstance(raw_config, dict) or not isinstance(raw_config.get("searches"), dict):
        raise ValueError("Search configuration must contain a 'searches' mapping")

    configs: dict[str, SearchConfig] = {}
    for name, values in raw_config["searches"].items():
        if not isinstance(values, dict):
            raise ValueError(f"Search {name!r} must be a mapping")

        allowed_fields = {"query", "region", "category", "max_pages", "enabled"}
        unknown_fields = set(values) - allowed_fields
        if unknown_fields:
            fields = ", ".join(sorted(unknown_fields))
            raise ValueError(f"Search {name!r} contains unknown fields: {fields}")

        try:
            configs[name] = SearchConfig(name=name, **values)
        except TypeError as exc:
            raise ValueError(f"Search {name!r} is missing required configuration: {exc}") from exc
        except ValueError as exc:
            raise ValueError(f"Invalid search {name!r}: {exc}") from exc

    if not configs:
        raise ValueError("Search configuration must define at least one search")

    return configs


def load_runtime_config(path: str | Path = DEFAULT_SEARCH_CONFIG_PATH) -> RuntimeConfig:
    raw_config = _load_raw_config(path)
    raw_runtime = raw_config.get("runtime", {})
    if not isinstance(raw_runtime, dict):
        raise ValueError("Runtime configuration must be a mapping")

    allowed_fields = {
        "headless",
        "browser_channel",
        "navigation_timeout_seconds",
        "page_settle_delay_seconds",
        "detail_delay_seconds",
        "max_retries",
        "retry_base_delay_seconds",
    }
    unknown_fields = set(raw_runtime) - allowed_fields
    if unknown_fields:
        fields = ", ".join(sorted(unknown_fields))
        raise ValueError(f"Runtime configuration contains unknown fields: {fields}")

    try:
        return RuntimeConfig(**raw_runtime)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid runtime configuration: {exc}") from exc


def load_application_config(
    path: str | Path = DEFAULT_SEARCH_CONFIG_PATH,
) -> tuple[dict[str, SearchConfig], RuntimeConfig]:
    return load_search_configs(path), load_runtime_config(path)


def select_search_config(
    configs: dict[str, SearchConfig], name: str | None = None
) -> SearchConfig:
    if name is not None:
        if name not in configs:
            available = ", ".join(configs) or "none"
            raise ValueError(f"Unknown search {name!r}. Available searches: {available}")
        selected = configs[name]
        if not selected.enabled:
            raise ValueError(f"Search {name!r} is disabled")
        return selected

    for config in configs.values():
        if config.enabled:
            return config

    raise ValueError("No enabled searches are configured")

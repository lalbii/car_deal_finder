from pathlib import Path

import yaml

from models.search_config import SearchConfig


DEFAULT_SEARCH_CONFIG_PATH = Path(__file__).with_name("searches.yaml")


def load_search_configs(path: str | Path = DEFAULT_SEARCH_CONFIG_PATH) -> dict[str, SearchConfig]:
    config_path = Path(path)

    try:
        raw_config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Search configuration file not found: {config_path}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in search configuration {config_path}: {exc}") from exc

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

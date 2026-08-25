from dataclasses import dataclass


@dataclass(frozen=True)
class SearchConfig:
    """A saved Kleinanzeigen search using URL-ready path values."""

    name: str
    query: str
    region: str
    category: str
    max_pages: int
    enabled: bool = True

    def __post_init__(self) -> None:
        for field_name in ("name", "query", "region", "category"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Search configuration {field_name!r} must not be empty")

        if isinstance(self.max_pages, bool) or not isinstance(self.max_pages, int):
            raise ValueError("Search configuration 'max_pages' must be an integer")
        if self.max_pages <= 0:
            raise ValueError("Search configuration 'max_pages' must be greater than zero")
        if not isinstance(self.enabled, bool):
            raise ValueError("Search configuration 'enabled' must be true or false")

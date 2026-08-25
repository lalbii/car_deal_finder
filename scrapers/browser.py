from models.runtime_config import RuntimeConfig


def launch_browser(playwright, runtime_config: RuntimeConfig):
    return playwright.chromium.launch(headless=runtime_config.headless)

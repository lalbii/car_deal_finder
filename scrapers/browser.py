from models.runtime_config import RuntimeConfig


def launch_browser(playwright, runtime_config: RuntimeConfig):
    launch_kwargs = {"headless": runtime_config.headless}
    if runtime_config.browser_channel:
        launch_kwargs["channel"] = runtime_config.browser_channel
    return playwright.chromium.launch(**launch_kwargs)

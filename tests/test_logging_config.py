import logging
import tempfile
import unittest
from logging.handlers import RotatingFileHandler
from pathlib import Path

from operations.logging_config import LOGGER_NAME, configure_logging


class LoggingConfigTests(unittest.TestCase):
    def test_console_and_bounded_file_handlers_are_configured(self):
        logger = logging.getLogger(LOGGER_NAME)
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)

        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "application.log"
            configured = configure_logging(log_path)
            rotating = [
                handler
                for handler in configured.handlers
                if isinstance(handler, RotatingFileHandler)
            ]

            self.assertEqual(len(configured.handlers), 2)
            self.assertEqual(len(rotating), 1)
            self.assertEqual(rotating[0].maxBytes, 5 * 1024 * 1024)
            self.assertEqual(rotating[0].backupCount, 3)
            self.assertTrue(log_path.exists())

        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)


if __name__ == "__main__":
    unittest.main()

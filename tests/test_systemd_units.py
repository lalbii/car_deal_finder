import unittest
from pathlib import Path

from config.paths import PROJECT_ROOT


SERVICE_PATH = PROJECT_ROOT / "deploy" / "systemd" / "car-deal-finder.service"
TIMER_PATH = PROJECT_ROOT / "deploy" / "systemd" / "car-deal-finder.timer"


class SystemdUnitTests(unittest.TestCase):
    def test_service_is_one_non_root_scrape_run_using_venv_python(self):
        service = SERVICE_PATH.read_text(encoding="utf-8")

        self.assertIn("Type=oneshot", service)
        self.assertIn("User=ubuntu", service)
        self.assertIn("WorkingDirectory=/opt/car_deal_finder", service)
        self.assertIn(
            "ExecStart=/opt/car_deal_finder/.venv/bin/python "
            "/opt/car_deal_finder/main.py --search bmw_320d_nrw",
            service,
        )
        self.assertIn("Environment=PYTHONUNBUFFERED=1", service)
        self.assertIn("TimeoutStartSec=2h", service)
        self.assertIn("Restart=no", service)
        self.assertIn("StandardOutput=journal", service)
        self.assertIn("StandardError=journal", service)
        self.assertNotIn("Restart=always", service)
        self.assertNotIn("playwright install", service)
        self.assertNotIn("[Install]", service)

    def test_timer_is_hourly_persistent_and_enabled_under_timers_target(self):
        timer = TIMER_PATH.read_text(encoding="utf-8")

        self.assertIn("OnCalendar=hourly", timer)
        self.assertIn("Persistent=true", timer)
        self.assertIn("Unit=car-deal-finder.service", timer)
        self.assertIn("WantedBy=timers.target", timer)


if __name__ == "__main__":
    unittest.main()

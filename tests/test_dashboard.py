import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

from dashboard.metrics import _bytes_per_second, _cpu_temperature
from dashboard.web import make_handler


class StubSampler:
    def read(self):
        return {"timestamp": 123, "cpu": {"percent": 42}}, [{"timestamp": 123, "cpu": 42}]


class DashboardTests(unittest.TestCase):
    def test_counter_reset_does_not_create_negative_traffic(self):
        self.assertEqual(_bytes_per_second(80, 100, 2), 0)
        self.assertEqual(_bytes_per_second(120, 100, 2), 10)

    @patch("dashboard.metrics.psutil.sensors_temperatures", create=True)
    def test_unidentified_thermal_zone_is_not_labeled_cpu_temperature(self, sensors):
        sensors.return_value = {"acpitz": [type("Reading", (), {"current": 49})()]}
        self.assertIsNone(_cpu_temperature())

    def test_api_and_static_routes(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(StubSampler()))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with urlopen(base + "/api/metrics") as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(json.load(response)["current"]["cpu"]["percent"], 42)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
            with urlopen(base + "/") as response:
                self.assertIn(b"Qwill", response.read())
            with self.assertRaises(HTTPError) as error:
                urlopen(base + "/.git/config")
            self.assertEqual(error.exception.code, 404)
            error.exception.close()
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()

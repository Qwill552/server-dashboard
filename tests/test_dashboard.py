import os
import tempfile
import threading
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from fastapi.testclient import TestClient

from dashboard.metrics import _bytes_per_second, _cpu_temperature
from dashboard.web import create_app


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
        with tempfile.TemporaryDirectory() as directory, TestClient(create_app(StubSampler(), Path(directory))) as client:
            response = client.get("/api/metrics")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["current"]["cpu"]["percent"], 42)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertEqual(client.get("/api/health").json()["status"], "ok")
            self.assertIn("Qwill", client.get("/").text)
            self.assertEqual(client.get("/console.js").status_code, 200)
            self.assertEqual(client.get("/manage.css").status_code, 200)
            self.assertEqual(client.get("/.git/config").status_code, 404)

    def test_file_save_conflict_and_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "settings.txt"
            target.write_bytes(b"before\n")
            with TestClient(create_app(StubSampler(), root / "state")) as client:
                listing = client.get("/api/files", params={"path": str(root)}).json()
                self.assertIn("settings.txt", [item["name"] for item in listing["entries"]])
                opened = client.get("/api/file", params={"path": str(target)}).json()
                saved = client.put("/api/file", json={"path": str(target), "content": "after\n", "revision": opened["revision"]})
                self.assertEqual(saved.status_code, 200)
                self.assertEqual(target.read_text(encoding="utf-8"), "after\n")
                self.assertEqual(client.put("/api/file", json={"path": str(target), "content": "stale", "revision": opened["revision"]}).status_code, 409)
                backups = client.get("/api/backups", params={"path": str(target)}).json()["backups"]
                self.assertEqual(len(backups), 1)
                restored = client.get("/api/backup", params={"path": str(target), "id": backups[0]["id"]}).json()
                self.assertEqual(restored["content"], "before\n")

    def test_macros_are_saved_and_stop_after_failed_command(self):
        with tempfile.TemporaryDirectory() as directory, TestClient(create_app(StubSampler(), Path(directory))) as client:
            self.assertIn("flush", [item["name"] for item in client.get("/api/macros").json()["macros"]])
            payload = {"label": "Check", "command": "echo ready", "file": "", "open_url": "https://example.com"}
            self.assertEqual(client.put("/api/macros/check", json=payload).status_code, 200)
            with patch("dashboard.macros.subprocess.run", return_value=CompletedProcess([], 0, "ready\n", "")):
                result = client.post("/api/macros/check/run").json()
            self.assertTrue(result["success"])
            self.assertEqual(result["open_url"], "https://example.com")
            with patch("dashboard.macros.subprocess.run", return_value=CompletedProcess([], 1, "", "failed\n")):
                result = client.post("/api/macros/check/run").json()
            self.assertFalse(result["success"])
            self.assertEqual(result["open_url"], "")
            self.assertEqual(client.delete("/api/macros/check").status_code, 200)
            self.assertEqual(client.post("/api/macros/check/run").status_code, 404)

    def test_macro_runs_command_then_executable_file(self):
        with tempfile.TemporaryDirectory() as directory, TestClient(create_app(StubSampler(), Path(directory))) as client:
            executable = str(Path(directory) / "task.sh")
            payload = {"label": "Two steps", "command": "echo first", "file": executable, "open_url": ""}
            self.assertEqual(client.put("/api/macros/two_steps", json=payload).status_code, 200)
            results = [CompletedProcess([], 0, "first\n", ""), CompletedProcess([], 0, "second\n", "")]
            with patch("dashboard.macros.subprocess.run", side_effect=results) as run:
                response = client.post("/api/macros/two_steps/run")
            self.assertEqual(response.status_code, 200)
            self.assertIn("second", response.json()["output"])
            self.assertEqual(run.call_count, 2)
            self.assertEqual(run.call_args_list[1].args[0], [executable])

    @unittest.skipUnless(os.name == "posix", "PTY terminal is Linux-only")
    def test_websocket_terminal_runs_a_command(self):
        with tempfile.TemporaryDirectory() as directory, TestClient(create_app(StubSampler(), Path(directory))) as client:
            with client.websocket_connect("/ws/terminal") as websocket:
                timer = threading.Timer(6, websocket.close)
                timer.daemon = True
                timer.start()
                try:
                    websocket.send_bytes(b"stty -echo; printf '\\x5f\\x5fPTY_OK\\x5f\\x5f'; exit\n")
                    output = bytearray()
                    while b"__PTY_OK__" not in output:
                        output.extend(websocket.receive_bytes())
                        self.assertLess(len(output), 100_000)
                finally:
                    timer.cancel()


if __name__ == "__main__":
    unittest.main()

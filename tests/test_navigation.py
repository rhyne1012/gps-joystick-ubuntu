"""Unit and FastAPI integration tests for GPS Joystick Ubuntu."""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from gps_joystick_ubuntu.navigation import DEFAULT_START, GeoPoint, NavigationEngine, StickInput
from gps_joystick_ubuntu.server import create_app


class GeoPointTests(unittest.TestCase):
    def test_moved_and_distance_north_east_roundtrip(self) -> None:
        origin = DEFAULT_START
        north = origin.moved(1000.0, 0.0)
        self.assertGreater(north.latitude, origin.latitude)
        self.assertAlmostEqual(north.longitude, origin.longitude, places=6)
        self.assertAlmostEqual(origin.distance_to(north), 1000.0, delta=0.5)

        east = origin.moved(500.0, 90.0)
        self.assertGreater(east.longitude, origin.longitude)
        self.assertAlmostEqual(origin.distance_to(east), 500.0, delta=0.5)

    def test_antimeridian_wrap(self) -> None:
        near_date_line = GeoPoint(latitude=0.0, longitude=179.999)
        wrapped = near_date_line.moved(500.0, 90.0)
        self.assertTrue(wrapped.is_valid())
        self.assertLess(wrapped.longitude, -179.0)


class StickInputTests(unittest.TestCase):
    def test_deadzone_and_unit_clamp(self) -> None:
        self.assertFalse(StickInput(0.05, 0.05).is_deflected)
        clamped = StickInput(3.0, 4.0)
        self.assertTrue(clamped.is_deflected)
        self.assertAlmostEqual(clamped.east, 0.6, places=6)
        self.assertAlmostEqual(clamped.north, 0.8, places=6)

    def test_cardinal_and_diagonal_bearings(self) -> None:
        self.assertAlmostEqual(StickInput(0.0, 1.0).bearing_deg, 0.0, places=5)
        self.assertAlmostEqual(StickInput(1.0, 0.0).bearing_deg, 90.0, places=5)
        self.assertAlmostEqual(StickInput(0.0, -1.0).bearing_deg, 180.0, places=5)
        self.assertAlmostEqual(StickInput(-1.0, 0.0).bearing_deg, 270.0, places=5)
        self.assertAlmostEqual(StickInput(1.0, 1.0).bearing_deg, 45.0, places=5)


class NavigationEngineTests(unittest.TestCase):
    def test_advancement_pause_resume_and_speed_clamp(self) -> None:
        nav = NavigationEngine()
        self.assertEqual(nav.motion, "awaiting_direction")
        self.assertFalse(nav.tick(0.1))

        nav.set_speed(999.0)
        self.assertEqual(nav.target_speed_kph, 120.0)
        nav.set_speed(-5.0)
        self.assertEqual(nav.target_speed_kph, 0.0)
        nav.set_speed(36.0)  # 10 m/s

        nav.set_stick(1.0, 0.0)  # East
        self.assertEqual(nav.motion, "moving")
        self.assertAlmostEqual(nav.bearing, 90.0, places=5)

        moved = nav.tick(0.25)  # 2.5m >= 2.0m step
        self.assertTrue(moved)
        self.assertAlmostEqual(nav.distance_m, 2.5, places=3)
        self.assertEqual(len(nav.trail), 2)

        nav.toggle_motion()
        self.assertEqual(nav.motion, "paused")
        self.assertEqual(nav.current_speed_kph, 0.0)
        self.assertFalse(nav.tick(0.2))

        nav.toggle_motion()
        self.assertEqual(nav.motion, "moving")
        self.assertEqual(nav.current_speed_kph, 36.0)

    def test_set_start_resets_trail_and_pauses(self) -> None:
        nav = NavigationEngine()
        nav.set_speed(36.0)
        nav.set_stick(0.0, 1.0)
        nav.tick(0.25)
        self.assertEqual(len(nav.trail), 2)

        new_point = GeoPoint(35.681236, 139.767125)
        self.assertTrue(nav.set_start(new_point))
        self.assertEqual(nav.position, new_point)
        self.assertEqual(nav.motion, "paused")
        self.assertEqual(nav.distance_m, 0.0)
        self.assertEqual(nav.trail, [new_point])

    def test_trail_cap(self) -> None:
        nav = NavigationEngine()
        nav.set_speed(120.0)  # 33.33 m/s -> ~8.33 m per 0.25s tick
        nav.set_stick(0.0, 1.0)
        for _ in range(1250):
            nav.tick(0.25)
        self.assertLessEqual(len(nav.trail), NavigationEngine.MAX_TRAIL_POINTS)


class ServerApiTests(unittest.TestCase):
    def test_http_and_websocket_controls(self) -> None:
        app = create_app()
        with TestClient(app) as client:
            home = client.get("/")
            self.assertEqual(home.status_code, 200)
            self.assertIn("GPS 搖桿", home.text)

            state = client.get("/api/state")
            self.assertEqual(state.status_code, 200)
            body = state.json()
            self.assertEqual(body["device"]["phase"], "idle")
            self.assertAlmostEqual(
                body["navigation"]["position"]["latitude"], DEFAULT_START.latitude, places=5
            )

            with client.websocket_connect("/ws") as ws:
                initial = ws.receive_json()
                self.assertEqual(initial["navigation"]["motion"], "awaiting_direction")

                ws.send_json({"action": "set_start", "latitude": 24.1618, "longitude": 120.6469})
                ws.send_json({"action": "speed", "speed_kph": 18.0})
                ws.send_json({"action": "stick", "east": 0.0, "north": 1.0})
                ws.send_json({"action": "toggle_motion"})

                latest = None
                for _ in range(10):
                    msg = ws.receive_json()
                    latest = msg
                    if (
                        abs(msg["navigation"]["position"]["latitude"] - 24.1618) < 0.01
                        and msg["navigation"]["target_speed_kph"] == 18.0
                        and msg["navigation"]["motion"] == "paused"
                    ):
                        break
                self.assertIsNotNone(latest)
                self.assertAlmostEqual(latest["navigation"]["position"]["latitude"], 24.1618, places=3)
                self.assertEqual(latest["navigation"]["target_speed_kph"], 18.0)
                self.assertEqual(latest["navigation"]["motion"], "paused")


if __name__ == "__main__":
    unittest.main()

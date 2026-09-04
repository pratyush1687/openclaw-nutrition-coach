import tempfile
import unittest

from app.config import configured_users, default_targets
from app.database import connect, init_db
from app.jobs_api import setup_status
from app.reminders.jobs import install_manifest


class ConfigUserTests(unittest.TestCase):
    def test_configured_users_uses_users_list(self):
        cfg = {
            "defaults": {"targets": {"calories_kcal": 2100, "protein_g": 110}},
            "users": [
                {"id": 1, "name": "A", "targets": {"calories_kcal": 1900}},
                {"id": 2, "name": "B", "targets": {"protein_g": 80}},
            ],
        }
        self.assertEqual([user["name"] for user in configured_users(cfg)], ["A", "B"])
        self.assertEqual(default_targets(cfg)["calories_kcal"], 2100)
        self.assertEqual(default_targets(cfg)["protein_g"], 110)

    def test_legacy_single_user_config_still_works(self):
        cfg = {
            "timezone": "Asia/Kolkata",
            "user": {"name": "Legacy"},
            "targets": {"calories_kcal": 2300, "protein_g": 150},
        }
        users = configured_users(cfg)
        self.assertEqual(len(users), 1)
        self.assertEqual(users[0]["name"], "Legacy")
        self.assertEqual(users[0]["targets"]["calories_kcal"], 2300)
        self.assertEqual(users[0]["targets"]["protein_g"], 150)

    def test_empty_users_list_disables_bootstrap_users(self):
        self.assertEqual(configured_users({"users": []}), [])

    def test_database_bootstraps_multiple_configured_users(self):
        cfg = {
            "timezone": "Asia/Kolkata",
            "defaults": {"targets": {"calories_kcal": 2000, "protein_g": 100, "fibre_g": 30, "water_l": 2.5, "steps": 8000}},
            "users": [
                {"id": 1, "name": "A", "telegram_user_id": "111", "age": 30, "height_cm": 170, "starting_weight_kg": 80, "goal_weight_kg": 70, "targets": {"calories_kcal": 1900}},
                {"id": 2, "name": "B", "telegram_user_id": "222", "targets": {"protein_g": 90}},
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            old_path = os.environ.get("DATABASE_PATH")
            os.environ["DATABASE_PATH"] = f"{tmpdir}/nutrition.sqlite"
            try:
                init_db(cfg)
                with connect() as conn:
                    users = conn.execute("SELECT id, name FROM users WHERE id > 0 ORDER BY id").fetchall()
                    self.assertEqual([(row["id"], row["name"]) for row in users], [(1, "A"), (2, "B")])
                    status = setup_status(conn, query={"telegram_user_id": ["111"]})
                    self.assertTrue(status["configured"])
                    unknown = setup_status(conn, query={"telegram_user_id": ["999"]})
                    self.assertTrue(unknown["needs_user"])
                    self.assertIn("starting_weight_kg", unknown["missing_profile_fields"])
            finally:
                if old_path is None:
                    os.environ.pop("DATABASE_PATH", None)
                else:
                    os.environ["DATABASE_PATH"] = old_path

    def test_automation_manifest_fans_out_to_active_users(self):
        cfg = """
timezone: Asia/Kolkata
defaults:
  targets:
    calories_kcal: 2000
    protein_g: 100
    fibre_g: 30
    water_l: 2.5
    steps: 8000
users:
  - id: 1
    name: Alpha
  - id: 2
    name: Beta
meal_windows:
  breakfast:
    reminders: ["10:30"]
schedule:
  morning_plan: "0 8 * * *"
  evening_scorecard: "30 22 * * *"
  weekly_summary: "0 9 * * 0"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            path = f"{tmpdir}/coach.yaml"
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(cfg)
            old_path = os.environ.get("COACH_CONFIG")
            os.environ["COACH_CONFIG"] = path
            try:
                jobs = install_manifest()
                names = {job["name"] for job in jobs}
                commands = "\n".join(job["command"] for job in jobs)
                self.assertIn("nutrition-morning-plan-all", names)
                self.assertIn("nutrition-breakfast-reminder-1-all", names)
                self.assertIn("/morning-plan-all?send=1", commands)
                self.assertIn("/check-meal?meal=breakfast", commands)
            finally:
                if old_path is None:
                    os.environ.pop("COACH_CONFIG", None)
                else:
                    os.environ["COACH_CONFIG"] = old_path


if __name__ == "__main__":
    unittest.main()

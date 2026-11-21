import os
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

import database
import main
import operations
import security
from security import create_access_token, get_current_user, hash_password


class OperationsWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.previous_database_path = database.DATABASE_PATH
        database.DATABASE_PATH = Path(self.temporary_directory.name) / "test.db"
        database.initialize_database()
        salt, password_hash, iterations = hash_password("test-password-123")
        with closing(database.get_connection()) as connection:
            with connection:
                cursor = connection.execute(
                    """
                    INSERT INTO users (
                        username, display_name, password_hash, password_salt,
                        password_iterations, role, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, 'administrator', ?)
                    """,
                    (
                        "admin",
                        "Test Administrator",
                        password_hash,
                        salt,
                        iterations,
                        database.utc_now(),
                    ),
                )
                self.admin_id = cursor.lastrowid
                self.admin = {
                    "user_id": self.admin_id,
                    "username": "admin",
                    "display_name": "Test Administrator",
                    "role": "administrator",
                    "department_id": None,
                    "is_active": 1,
                }
                connection.execute(
                    """
                    INSERT INTO users (
                        username, display_name, password_hash, password_salt,
                        password_iterations, role, department_id, created_at
                    )
                    VALUES ('worker', 'Test Worker', ?, ?, ?, 'field_worker', 'water', ?)
                    """,
                    (password_hash, salt, iterations, database.utc_now()),
                )
                self.worker_id = connection.execute(
                    "SELECT user_id FROM users WHERE username='worker'"
                ).fetchone()["user_id"]
                connection.execute(
                    """
                    INSERT INTO users (
                        username, display_name, password_hash, password_salt,
                        password_iterations, role, department_id, created_at
                    )
                    VALUES ('official', 'Test Official', ?, ?, ?, 'department_official', 'water', ?)
                    """,
                    (password_hash, salt, iterations, database.utc_now()),
                )
                self.official_id = connection.execute(
                    "SELECT user_id FROM users WHERE username='official'"
                ).fetchone()["user_id"]
        self.worker = {
            "user_id": self.worker_id,
            "username": "worker",
            "display_name": "Test Worker",
            "role": "field_worker",
            "department_id": "water",
            "is_active": 1,
        }
        self.official = {
            "user_id": self.official_id,
            "username": "official",
            "display_name": "Test Official",
            "role": "department_official",
            "department_id": "water",
            "is_active": 1,
        }

    def tearDown(self):
        database.DATABASE_PATH = self.previous_database_path
        self.temporary_directory.cleanup()

    def test_complaint_rejects_pending_area_and_groups_duplicates(self):
        pending = operations.register_area(
            operations.AreaCreate(area_name="Test Bay", ward_code="TB-1"),
            self.admin,
        )
        complaint = operations.ComplaintCreate(
            area_id=pending["area_id"],
            issue_category="water",
            description="Water supply has stopped on the main road since this morning.",
            reporter_name="Resident",
        )
        with self.assertRaises(HTTPException) as raised:
            operations.create_citizen_complaint(complaint, {"user_id": 25, "display_name": "Resident"})
        self.assertEqual(raised.exception.status_code, 422)

        with closing(database.get_connection()) as connection:
            area_id = connection.execute(
                "SELECT area_id FROM registered_areas WHERE area_name='Panaji'"
            ).fetchone()["area_id"]
        first = operations.ComplaintCreate(
            area_id=area_id,
            issue_category="water",
            description="Water supply stopped on the main road since this morning.",
            reporter_name="Resident One",
        )
        second = operations.ComplaintCreate(
            area_id=area_id,
            issue_category="water",
            description="Water supply stopped on the main road since this morning!",
            reporter_name="Resident Two",
        )
        user = {"user_id": self.admin_id, "display_name": "Test Administrator"}
        first_result = operations._create_complaint(first, "Resident One", "municipal_staff", self.admin_id)
        second_result = operations._create_complaint(second, "Resident Two", "municipal_staff", self.admin_id)
        self.assertFalse(first_result["duplicate_grouped"])
        self.assertTrue(second_result["duplicate_grouped"])
        self.assertEqual(second_result["report_count"], 2)
        summary = operations.incidents_summary(self.admin)
        self.assertEqual(summary["reported_complaints"], 2)
        self.assertEqual(summary["open_incidents"], 1)

    def test_unresolved_incident_is_escalated_through_all_configured_levels(self):
        with closing(database.get_connection()) as connection:
            area_id = connection.execute(
                "SELECT area_id FROM registered_areas WHERE area_name='Panaji'"
            ).fetchone()["area_id"]
        report = operations.ComplaintCreate(
            area_id=area_id,
            issue_category="water",
            description="Water supply has failed near the library since the afternoon.",
            reporter_name="Resident",
        )
        incident = operations._create_complaint(
            report, "Resident", "municipal_staff", self.admin_id
        )
        with closing(database.get_connection()) as connection:
            with connection:
                connection.execute(
                    "UPDATE incidents SET created_at=? WHERE incident_id=?",
                    (
                        (datetime.now(timezone.utc) - timedelta(hours=8)).isoformat(),
                        incident["incident_id"],
                    ),
                )
        operations.run_escalations()
        operations.run_escalations()
        operations.run_escalations()
        with closing(database.get_connection()) as connection:
            levels = [
                row["level"]
                for row in connection.execute(
                    "SELECT level FROM escalation_history WHERE incident_id=? ORDER BY level",
                    (incident["incident_id"],),
                )
            ]
        self.assertEqual(levels, [1, 2, 3])

    def test_weather_fallback_never_claims_an_external_provider(self):
        status = operations.weather_status(user=self.admin)
        self.assertFalse(status["provider_configured"])
        self.assertEqual(status["provider_status"], "not_configured")
        self.assertIn("explicitly supplied", status["fallback"])

    def test_new_area_needs_three_recorded_observations_before_verification(self):
        result = operations.register_area(
            operations.AreaCreate(area_name="Test Bay", ward_code="TB-2"),
            self.admin,
        )
        area_id = result["area_id"]
        with self.assertRaises(HTTPException) as raised:
            operations.verify_area(
                area_id, operations.AreaVerification(verified=True, model_ready=True), self.admin
            )
        self.assertEqual(raised.exception.status_code, 422)

        base_time = datetime.now(timezone.utc) - timedelta(hours=1)
        values = {
            "source": "Municipal field visit",
            "rainfall_mm": 4,
            "temperature_c": 27,
            "humidity_pct": 70,
            "water_supply_hours": 8,
            "water_pressure": 50,
            "missed_pickups": 0,
            "collection_frequency_per_week": 3,
            "complaints_count": 1,
            "pipeline_age_years": 10,
            "drainage_capacity_pct": 75,
            "previous_repairs_6m": 0,
        }
        for day in range(3):
            observation = operations.AreaDataObservation(
                observed_at=base_time - timedelta(days=day),
                **values,
            )
            operations.record_area_observation(area_id, observation, self.admin)

        with self.assertRaises(HTTPException) as duplicate:
            operations.record_area_observation(
                area_id,
                operations.AreaDataObservation(
                    observed_at=base_time,
                    **values,
                ),
                self.admin,
            )
        self.assertEqual(duplicate.exception.status_code, 409)

        verified = operations.verify_area(
            area_id, operations.AreaVerification(verified=True, model_ready=True), self.admin
        )
        self.assertEqual(verified["status"], "verified")
        self.assertEqual(verified["valid_data_points"], 3)
        self.assertTrue(verified["model_ready"])

    def test_worker_completion_requires_supervisor_verification(self):
        with closing(database.get_connection()) as connection:
            area_id = connection.execute(
                "SELECT area_id FROM registered_areas WHERE area_name='Panaji'"
            ).fetchone()["area_id"]
        complaint = operations.ComplaintCreate(
            area_id=area_id,
            issue_category="water",
            description="A supply valve is damaged and water is leaking near the market.",
            reporter_name="Resident",
            priority="high",
        )
        record = operations._create_complaint(
            complaint, "Resident", "municipal_staff", self.admin_id
        )
        assignment = operations.IncidentAssignment(
            department_id="water",
            responsible_user_id=self.worker_id,
            task_details="Inspect the damaged valve and repair the reported water leak.",
        )
        assigned = operations.assign_incident(record["incident_id"], assignment, self.admin)
        with self.assertRaises(HTTPException) as raised:
            operations.update_task(
                assigned["task_id"],
                operations.TaskUpdate(status="completed", completion_details=""),
                self.worker,
            )
        self.assertEqual(raised.exception.status_code, 422)

        completed = operations.update_task(
            assigned["task_id"],
            operations.TaskUpdate(
                status="completed",
                completion_details="Valve isolated and temporary repair completed.",
            ),
            self.worker,
        )
        self.assertEqual(completed["status"], "verification_required")
        verified = operations.verify_task(
            assigned["task_id"],
            operations.TaskVerification(verified=True, notes="Repair inspected and confirmed."),
            self.official,
        )
        self.assertEqual(verified["status"], "verified")

    def test_critical_notification_promotes_existing_routine_queue_entry(self):
        with closing(database.get_connection()) as connection:
            with connection:
                incident_id = "test-incident"
                area_id = connection.execute(
                    "SELECT area_id FROM registered_areas WHERE area_name='Panaji'"
                ).fetchone()["area_id"]
                now = database.utc_now()
                connection.execute(
                    """
                    INSERT INTO incidents (
                        incident_id, area_id, issue_category, description,
                        complaint_source, priority, primary_department_id,
                        due_at, created_at, updated_at
                    )
                    VALUES (?, ?, 'water', 'test incident', 'municipal_staff',
                            'high', 'water', ?, ?, ?)
                    """,
                    (incident_id, area_id, now, now, now),
                )
                operations._queue_notification(connection, incident_id, "water", "routine")
                operations._queue_notification(connection, incident_id, "water", "critical")
                notification = connection.execute(
                    """
                    SELECT urgency, status FROM notifications
                    WHERE incident_id=? AND department_id='water'
                    """,
                    (incident_id,),
                ).fetchone()
        self.assertEqual(notification["urgency"], "critical")
        self.assertEqual(notification["status"], "internal_queued")

    def test_auth_token_requires_configured_secret_and_active_user(self):
        previous_secret = os.environ.get("CIVICPREDICT_SECRET_KEY")
        previous_demo_mode = security.DEMO_MODE
        security.DEMO_MODE = False
        os.environ["CIVICPREDICT_SECRET_KEY"] = "test-secret-value-that-is-at-least-32-bytes"
        try:
            token = create_access_token(self.admin_id)
            user = get_current_user(
                HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
            )
            self.assertEqual(user["role"], "administrator")
        finally:
            security.DEMO_MODE = previous_demo_mode
            if previous_secret is None:
                os.environ.pop("CIVICPREDICT_SECRET_KEY", None)
            else:
                os.environ["CIVICPREDICT_SECRET_KEY"] = previous_secret

    def test_demo_mode_allows_routes_without_credentials_and_keeps_roles_table(self):
        demo_user = get_current_user()
        self.assertEqual(demo_user["role"], "administrator")
        self.assertEqual(demo_user["display_name"], "Demo Operator")
        self.assertEqual(
            security.require_roles("citizen")(demo_user)["role"],
            "citizen",
        )
        self.assertTrue(main.demo_status()["demo_mode"])
        self.assertFalse(main.demo_status()["authentication_required"])
        self.assertEqual(len(operations.list_areas(demo_user)["areas"]), 15)
        self.assertIn("departments", operations.list_departments(demo_user))
        self.assertIn("incidents", operations.list_incidents(user=demo_user))
        self.assertIn("alerts", operations.list_alerts(demo_user))
        self.assertIn("tasks", operations.list_tasks(user=demo_user))
        self.assertIn("history", main.get_prediction_history(demo_user))
        with closing(database.get_connection()) as connection:
            tables = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        self.assertIn("users", tables)

    def test_prediction_success_is_persisted_once_and_unknown_area_is_not_saved(self):
        prediction_input = {
            "ward_name": "Panaji",
            "rainfall_mm": 80,
            "temperature_c": 29,
            "humidity_pct": 75,
            "water_supply_hours": 7,
            "water_pressure": 48,
            "missed_pickups": 1,
            "collection_frequency_per_week": 4,
            "complaints_count": 3,
            "pipeline_age_years": 12,
            "drainage_capacity_pct": 72,
            "previous_repairs_6m": 1,
        }
        with closing(database.get_connection()) as connection:
            before_count = connection.execute(
                "SELECT COUNT(*) FROM prediction_history"
            ).fetchone()[0]

        result = main.predict(main.CivicData(**prediction_input), self.admin)

        with closing(database.get_connection()) as connection:
            after_count = connection.execute(
                "SELECT COUNT(*) FROM prediction_history"
            ).fetchone()[0]
            row = connection.execute(
                "SELECT requested_by, ward_name FROM prediction_history WHERE prediction_id=?",
                (result["prediction_id"],),
            ).fetchone()
        self.assertEqual(after_count, before_count + 1)
        self.assertEqual(row["requested_by"], self.admin_id)
        self.assertEqual(row["ward_name"], "Panaji")

        pending_area = operations.register_area(
            operations.AreaCreate(area_name="Prediction Test Area", ward_code="PTA-1"),
            self.admin,
        )
        prediction_input["ward_name"] = pending_area["area_name"]
        with self.assertRaises(HTTPException) as pending:
            main.predict(main.CivicData(**prediction_input), self.admin)
        self.assertEqual(pending.exception.status_code, 400)
        self.assertIn("Unsupported area", pending.exception.detail)

        prediction_input["ward_name"] = "Unregistered Place"
        with self.assertRaises(HTTPException) as raised:
            main.predict(main.CivicData(**prediction_input), self.admin)
        self.assertEqual(raised.exception.status_code, 400)
        with closing(database.get_connection()) as connection:
            final_count = connection.execute(
                "SELECT COUNT(*) FROM prediction_history"
            ).fetchone()[0]
        self.assertEqual(final_count, after_count)

    def test_all_supported_areas_predict_and_normalize_case_and_whitespace(self):
        prediction_input = {
            "ward_name": "",
            "rainfall_mm": 80,
            "temperature_c": 29,
            "humidity_pct": 75,
            "water_supply_hours": 7,
            "water_pressure": 48,
            "missed_pickups": 1,
            "collection_frequency_per_week": 4,
            "complaints_count": 3,
            "pipeline_age_years": 12,
            "drainage_capacity_pct": 72,
            "previous_repairs_6m": 1,
        }

        self.assertEqual(len(database.SUPPORTED_AREAS), 15)
        for area in database.SUPPORTED_AREAS:
            with self.subTest(area=area):
                prediction_input["ward_name"] = area
                result = main.predict(
                    main.CivicData(**prediction_input),
                    self.admin,
                )
                self.assertEqual(result["area"], area)

        prediction_input["ward_name"] = "  pAnAjI  "
        normalized_result = main.predict(
            main.CivicData(**prediction_input),
            self.admin,
        )
        self.assertEqual(normalized_result["area"], "Panaji")

    def test_unsupported_area_is_rejected_without_saving_history(self):
        prediction_input = {
            "ward_name": "Hyderabad",
            "rainfall_mm": 80,
            "temperature_c": 29,
            "humidity_pct": 75,
            "water_supply_hours": 7,
            "water_pressure": 48,
            "missed_pickups": 1,
            "collection_frequency_per_week": 4,
            "complaints_count": 3,
            "pipeline_age_years": 12,
            "drainage_capacity_pct": 72,
            "previous_repairs_6m": 1,
        }
        with closing(database.get_connection()) as connection:
            before_count = connection.execute(
                "SELECT COUNT(*) FROM prediction_history"
            ).fetchone()[0]

        with self.assertRaises(HTTPException) as raised:
            main.predict(main.CivicData(**prediction_input), self.admin)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("Unsupported area", raised.exception.detail)
        self.assertIn("Panaji", raised.exception.detail)
        with closing(database.get_connection()) as connection:
            after_count = connection.execute(
                "SELECT COUNT(*) FROM prediction_history"
            ).fetchone()[0]
        self.assertEqual(after_count, before_count)


if __name__ == "__main__":
    unittest.main()

from contextlib import closing
from pathlib import Path
import sqlite3
from datetime import datetime, timezone


DATABASE_PATH = Path(__file__).resolve().parent / "civicpredict.db"
SCHEMA_VERSION = 3

SUPPORTED_AREAS = (
    "Bicholim",
    "Calangute",
    "Canacona",
    "Candolim",
    "Curchorem",
    "Mapusa",
    "Margao",
    "Panaji",
    "Pernem",
    "Ponda",
    "Porvorim",
    "Quepem",
    "Sanguem",
    "Valpoi",
    "Vasco da Gama",
)

INITIAL_AREAS = SUPPORTED_AREAS

INITIAL_DEPARTMENTS = [
    ("water", "Water Supply", "water"),
    ("waste", "Waste Management", "waste"),
    ("drainage", "Drainage", "drainage"),
    ("municipal", "Municipal Operations", "other"),
]

MIGRATION_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS prediction_history (
        prediction_id INTEGER PRIMARY KEY AUTOINCREMENT,
        ward_name TEXT NOT NULL,
        prediction_datetime TEXT NOT NULL,
        rainfall_mm REAL NOT NULL,
        temperature_c REAL NOT NULL,
        humidity_pct REAL NOT NULL,
        water_supply_hours REAL NOT NULL,
        water_pressure REAL NOT NULL,
        missed_pickups INTEGER NOT NULL,
        collection_frequency_per_week INTEGER NOT NULL,
        complaints_count INTEGER NOT NULL,
        pipeline_age_years INTEGER NOT NULL,
        drainage_capacity_pct REAL NOT NULL,
        previous_repairs_6m INTEGER NOT NULL,
        water_supply_risk TEXT NOT NULL,
        waste_management_risk TEXT NOT NULL,
        drainage_risk TEXT NOT NULL,
        requested_by INTEGER REFERENCES users(user_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_prediction_history_datetime
    ON prediction_history (prediction_datetime DESC, prediction_id DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS departments (
        department_id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        category TEXT NOT NULL UNIQUE,
        is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS registered_areas (
        area_id TEXT PRIMARY KEY,
        area_name TEXT NOT NULL COLLATE NOCASE UNIQUE,
        ward_code TEXT COLLATE NOCASE UNIQUE,
        status TEXT NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending', 'verified')),
        model_ready INTEGER NOT NULL DEFAULT 0 CHECK (model_ready IN (0, 1)),
        valid_data_points INTEGER NOT NULL DEFAULT 0 CHECK (valid_data_points >= 0),
        created_by INTEGER,
        verified_by INTEGER,
        created_at TEXT NOT NULL,
        verified_at TEXT,
        FOREIGN KEY (created_by) REFERENCES users(user_id),
        FOREIGN KEY (verified_by) REFERENCES users(user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS area_data_observations (
        observation_id TEXT PRIMARY KEY,
        area_id TEXT NOT NULL,
        source TEXT NOT NULL,
        observed_at TEXT NOT NULL,
        data_json TEXT NOT NULL,
        recorded_by INTEGER NOT NULL,
        recorded_at TEXT NOT NULL,
        FOREIGN KEY (area_id) REFERENCES registered_areas(area_id),
        FOREIGN KEY (recorded_by) REFERENCES users(user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL COLLATE NOCASE UNIQUE,
        display_name TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        password_salt TEXT NOT NULL,
        password_iterations INTEGER NOT NULL,
        role TEXT NOT NULL CHECK (
            role IN ('administrator', 'department_official', 'field_worker', 'citizen')
        ),
        department_id TEXT,
        is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
        created_by INTEGER,
        created_at TEXT NOT NULL,
        FOREIGN KEY (department_id) REFERENCES departments(department_id),
        FOREIGN KEY (created_by) REFERENCES users(user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS area_corrections (
        correction_id TEXT PRIMARY KEY,
        area_id TEXT NOT NULL,
        previous_name TEXT NOT NULL,
        corrected_name TEXT NOT NULL,
        previous_ward_code TEXT,
        corrected_ward_code TEXT,
        correction_reason TEXT NOT NULL,
        corrected_by INTEGER NOT NULL,
        corrected_at TEXT NOT NULL,
        FOREIGN KEY (area_id) REFERENCES registered_areas(area_id),
        FOREIGN KEY (corrected_by) REFERENCES users(user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS incidents (
        incident_id TEXT PRIMARY KEY,
        area_id TEXT NOT NULL,
        issue_category TEXT NOT NULL CHECK (
            issue_category IN ('water', 'waste', 'drainage', 'other', 'ai_warning')
        ),
        description TEXT NOT NULL,
        complaint_source TEXT NOT NULL CHECK (
            complaint_source IN ('citizen', 'municipal_staff', 'field_worker', 'ai_warning')
        ),
        priority TEXT NOT NULL CHECK (priority IN ('low', 'medium', 'high', 'critical')),
        ai_risk_assessment TEXT,
        prediction_id INTEGER,
        primary_department_id TEXT NOT NULL,
        responsible_user_id INTEGER,
        status TEXT NOT NULL DEFAULT 'open' CHECK (
            status IN ('open', 'acknowledged', 'in_progress', 'verification_required', 'resolved', 'closed')
        ),
        report_count INTEGER NOT NULL DEFAULT 1 CHECK (report_count >= 1),
        due_at TEXT NOT NULL,
        resolution_details TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        resolved_at TEXT,
        FOREIGN KEY (area_id) REFERENCES registered_areas(area_id),
        FOREIGN KEY (prediction_id) REFERENCES prediction_history(prediction_id),
        FOREIGN KEY (primary_department_id) REFERENCES departments(department_id),
        FOREIGN KEY (responsible_user_id) REFERENCES users(user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS complaints (
        complaint_id TEXT PRIMARY KEY,
        incident_id TEXT NOT NULL,
        reporter_name TEXT NOT NULL,
        reporter_contact TEXT,
        complaint_source TEXT NOT NULL CHECK (
            complaint_source IN ('citizen', 'municipal_staff', 'field_worker')
        ),
        description TEXT NOT NULL,
        submitted_by INTEGER,
        duplicate_similarity REAL,
        submitted_at TEXT NOT NULL,
        FOREIGN KEY (incident_id) REFERENCES incidents(incident_id),
        FOREIGN KEY (submitted_by) REFERENCES users(user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS incident_departments (
        incident_id TEXT NOT NULL,
        department_id TEXT NOT NULL,
        is_primary INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0, 1)),
        acknowledged_by INTEGER,
        acknowledged_at TEXT,
        PRIMARY KEY (incident_id, department_id),
        FOREIGN KEY (incident_id) REFERENCES incidents(incident_id),
        FOREIGN KEY (department_id) REFERENCES departments(department_id),
        FOREIGN KEY (acknowledged_by) REFERENCES users(user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS assigned_tasks (
        task_id TEXT PRIMARY KEY,
        incident_id TEXT NOT NULL,
        department_id TEXT NOT NULL,
        assigned_user_id INTEGER,
        status TEXT NOT NULL DEFAULT 'pending' CHECK (
            status IN ('pending', 'in_progress', 'completed', 'verification_required', 'verified')
        ),
        task_details TEXT NOT NULL,
        due_at TEXT NOT NULL,
        created_by INTEGER,
        updated_by INTEGER,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (incident_id) REFERENCES incidents(incident_id),
        FOREIGN KEY (department_id) REFERENCES departments(department_id),
        FOREIGN KEY (assigned_user_id) REFERENCES users(user_id),
        FOREIGN KEY (created_by) REFERENCES users(user_id),
        FOREIGN KEY (updated_by) REFERENCES users(user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS work_completion_records (
        completion_id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        submitted_by INTEGER NOT NULL,
        completion_details TEXT NOT NULL,
        completion_status TEXT NOT NULL DEFAULT 'verification_required' CHECK (
            completion_status IN ('verification_required', 'verified', 'rejected')
        ),
        submitted_at TEXT NOT NULL,
        verified_by INTEGER,
        verification_notes TEXT,
        verified_at TEXT,
        FOREIGN KEY (task_id) REFERENCES assigned_tasks(task_id),
        FOREIGN KEY (submitted_by) REFERENCES users(user_id),
        FOREIGN KEY (verified_by) REFERENCES users(user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS alerts (
        alert_id TEXT PRIMARY KEY,
        incident_id TEXT NOT NULL UNIQUE,
        severity TEXT NOT NULL CHECK (severity IN ('high', 'critical')),
        status TEXT NOT NULL DEFAULT 'open' CHECK (
            status IN ('open', 'acknowledged', 'resolved')
        ),
        created_at TEXT NOT NULL,
        acknowledged_by INTEGER,
        acknowledged_at TEXT,
        resolved_at TEXT,
        FOREIGN KEY (incident_id) REFERENCES incidents(incident_id),
        FOREIGN KEY (acknowledged_by) REFERENCES users(user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS notifications (
        notification_id TEXT PRIMARY KEY,
        incident_id TEXT NOT NULL,
        department_id TEXT NOT NULL,
        urgency TEXT NOT NULL CHECK (urgency IN ('routine', 'critical')),
        status TEXT NOT NULL CHECK (
            status IN ('scheduled', 'internal_queued', 'acknowledged', 'cancelled')
        ),
        scheduled_for TEXT NOT NULL,
        created_at TEXT NOT NULL,
        acknowledged_by INTEGER,
        acknowledged_at TEXT,
        FOREIGN KEY (incident_id) REFERENCES incidents(incident_id),
        FOREIGN KEY (department_id) REFERENCES departments(department_id),
        FOREIGN KEY (acknowledged_by) REFERENCES users(user_id),
        UNIQUE (incident_id, department_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS escalation_history (
        escalation_id TEXT PRIMARY KEY,
        incident_id TEXT NOT NULL,
        level INTEGER NOT NULL CHECK (level BETWEEN 1 AND 3),
        recipient_role TEXT NOT NULL,
        reason TEXT NOT NULL,
        escalated_at TEXT NOT NULL,
        FOREIGN KEY (incident_id) REFERENCES incidents(incident_id),
        UNIQUE (incident_id, level)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS prediction_feedback (
        feedback_id TEXT PRIMARY KEY,
        prediction_id INTEGER NOT NULL,
        incident_id TEXT,
        outcome TEXT NOT NULL CHECK (outcome IN ('failure', 'no_failure', 'unknown')),
        feedback_notes TEXT NOT NULL,
        submitted_by INTEGER NOT NULL,
        submitted_at TEXT NOT NULL,
        FOREIGN KEY (prediction_id) REFERENCES prediction_history(prediction_id),
        FOREIGN KEY (incident_id) REFERENCES incidents(incident_id),
        FOREIGN KEY (submitted_by) REFERENCES users(user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS weather_observations (
        observation_id TEXT PRIMARY KEY,
        area_id TEXT NOT NULL,
        source TEXT NOT NULL,
        observed_at TEXT NOT NULL,
        received_at TEXT NOT NULL,
        rainfall_mm REAL,
        temperature_c REAL,
        humidity_pct REAL,
        notes TEXT,
        FOREIGN KEY (area_id) REFERENCES registered_areas(area_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS system_settings (
        setting_key TEXT PRIMARY KEY,
        setting_value TEXT NOT NULL,
        updated_by INTEGER,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (updated_by) REFERENCES users(user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_logs (
        audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        action TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        entity_id TEXT,
        details TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(user_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_areas_status ON registered_areas(status, area_name)",
    "CREATE INDEX IF NOT EXISTS idx_area_data_area_time ON area_data_observations(area_id, observed_at DESC)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_area_data_unique_observation ON area_data_observations(area_id, observed_at)",
    "CREATE INDEX IF NOT EXISTS idx_users_role_department ON users(role, department_id, is_active)",
    "CREATE INDEX IF NOT EXISTS idx_incidents_status_priority ON incidents(status, priority, due_at)",
    "CREATE INDEX IF NOT EXISTS idx_incidents_area_created ON incidents(area_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_complaints_incident_time ON complaints(incident_id, submitted_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_tasks_assignee_status_due ON assigned_tasks(assigned_user_id, status, due_at)",
    "CREATE INDEX IF NOT EXISTS idx_tasks_department_due ON assigned_tasks(department_id, status, due_at)",
    "CREATE INDEX IF NOT EXISTS idx_alerts_status_created ON alerts(status, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_notifications_status_schedule ON notifications(status, scheduled_for)",
    "CREATE INDEX IF NOT EXISTS idx_escalations_incident_time ON escalation_history(incident_id, escalated_at)",
    "CREATE INDEX IF NOT EXISTS idx_feedback_prediction ON prediction_feedback(prediction_id, submitted_at)",
    "CREATE INDEX IF NOT EXISTS idx_weather_area_time ON weather_observations(area_id, observed_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_audit_entity_time ON audit_logs(entity_type, entity_id, created_at DESC)",
]


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def get_connection():
    connection = sqlite3.connect(DATABASE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


def initialize_database():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(get_connection()) as connection:
        with connection:
            current_version = connection.execute(
                "PRAGMA user_version"
            ).fetchone()[0]
            if current_version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Database schema version {current_version} is newer than "
                    f"this application supports ({SCHEMA_VERSION})."
                )
            if current_version < SCHEMA_VERSION:
                for statement in MIGRATION_STATEMENTS:
                    connection.execute(statement)
                prediction_columns = {
                    row["name"]
                    for row in connection.execute(
                        "PRAGMA table_info(prediction_history)"
                    )
                }
                if "requested_by" not in prediction_columns:
                    connection.execute(
                        """
                        ALTER TABLE prediction_history
                        ADD COLUMN requested_by INTEGER REFERENCES users(user_id)
                        """
                    )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_prediction_history_owner
                    ON prediction_history (requested_by, prediction_datetime DESC)
                    """
                )
                connection.execute(
                    "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (SCHEMA_VERSION, utc_now()),
                )
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

            now = utc_now()
            connection.executemany(
                """
                INSERT OR IGNORE INTO departments (
                    department_id, name, category, created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                [(key, name, category, now) for key, name, category in INITIAL_DEPARTMENTS],
            )
            connection.executemany(
                """
                INSERT OR IGNORE INTO registered_areas (
                    area_id, area_name, status, model_ready, valid_data_points,
                    created_at, verified_at
                )
                VALUES (?, ?, 'verified', 1, 0, ?, ?)
                """,
                [
                    (f"goa-{index:02d}", area, now, now)
                    for index, area in enumerate(INITIAL_AREAS, start=1)
                ],
            )
            connection.execute(
                """
                UPDATE registered_areas
                SET valid_data_points = (
                    SELECT COUNT(*)
                    FROM area_data_observations
                    WHERE area_data_observations.area_id = registered_areas.area_id
                )
                """
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO system_settings (
                    setting_key, setting_value, updated_at
                )
                VALUES ('working_hours_start', '09:00', ?)
                """,
                (now,),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO system_settings (
                    setting_key, setting_value, updated_at
                )
                VALUES ('working_hours_end', '17:00', ?)
                """,
                (now,),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO system_settings (
                    setting_key, setting_value, updated_at
                )
                VALUES ('working_days', '0,1,2,3,4', ?)
                """,
                (now,),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO system_settings (
                    setting_key, setting_value, updated_at
                )
                VALUES ('weather_max_age_hours', '6', ?)
                """,
                (now,),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO system_settings (
                    setting_key, setting_value, updated_at
                )
                VALUES ('routine_acknowledgement_hours', '4', ?)
                """,
                (now,),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO system_settings (
                    setting_key, setting_value, updated_at
                )
                VALUES ('escalation_level_1_minutes', '30', ?)
                """,
                (now,),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO system_settings (
                    setting_key, setting_value, updated_at
                )
                VALUES ('escalation_level_2_minutes', '120', ?)
                """,
                (now,),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO system_settings (
                    setting_key, setting_value, updated_at
                )
                VALUES ('escalation_level_3_minutes', '360', ?)
                """,
                (now,),
            )


from contextlib import closing
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
import json
import sqlite3
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from database import get_connection, utc_now
from security import (
    DEMO_MODE,
    DEMO_USERNAME,
    create_access_token,
    hash_password,
    require_roles,
    verify_password,
)


router = APIRouter()
ADMIN = require_roles("administrator")
STAFF = require_roles("administrator", "department_official")
FIELD = require_roles("administrator", "department_official", "field_worker")
AUTHENTICATED = require_roles(
    "administrator", "department_official", "field_worker", "citizen"
)
GOA_TIMEZONE = ZoneInfo("Asia/Kolkata")
CATEGORIES = {"water", "waste", "drainage", "other"}
ACTIVE_INCIDENT_STATUSES = (
    "open", "acknowledged", "in_progress", "verification_required"
)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[a-zA-Z0-9._-]+$")
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=12, max_length=256)
    role: str
    department_id: str | None = None


class UserUpdate(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    role: str
    department_id: str | None = None
    is_active: bool


class AreaCreate(BaseModel):
    area_name: str = Field(min_length=2, max_length=120)
    ward_code: str | None = Field(default=None, max_length=40)


class AreaVerification(BaseModel):
    verified: bool
    model_ready: bool = False


class AreaDataObservation(BaseModel):
    source: str = Field(min_length=2, max_length=120)
    observed_at: datetime
    rainfall_mm: float = Field(ge=0)
    temperature_c: float = Field(ge=-50, le=60)
    humidity_pct: float = Field(ge=0, le=100)
    water_supply_hours: float = Field(ge=0, le=24)
    water_pressure: float = Field(ge=0)
    missed_pickups: int = Field(ge=0)
    collection_frequency_per_week: int = Field(ge=0, le=7)
    complaints_count: int = Field(ge=0)
    pipeline_age_years: int = Field(ge=0)
    drainage_capacity_pct: float = Field(ge=0, le=100)
    previous_repairs_6m: int = Field(ge=0)


class AreaCorrection(BaseModel):
    area_name: str = Field(min_length=2, max_length=120)
    ward_code: str | None = Field(default=None, max_length=40)
    reason: str = Field(min_length=5, max_length=500)


class DepartmentCreate(BaseModel):
    department_id: str = Field(min_length=2, max_length=40, pattern=r"^[a-z0-9_-]+$")
    name: str = Field(min_length=2, max_length=120)
    category: str = Field(min_length=2, max_length=40)


class DepartmentUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    is_active: bool


class ComplaintCreate(BaseModel):
    area_id: str = Field(min_length=1, max_length=80)
    issue_category: str
    description: str = Field(min_length=10, max_length=4000)
    reporter_name: str = Field(min_length=1, max_length=120)
    reporter_contact: str | None = Field(default=None, max_length=120)
    priority: str = "medium"


class IncidentAssignment(BaseModel):
    department_id: str
    responsible_user_id: int | None = None
    task_details: str = Field(min_length=5, max_length=2000)
    due_at: datetime | None = None


class SupportingDepartments(BaseModel):
    department_ids: list[str] = Field(min_length=1, max_length=10)


class TaskUpdate(BaseModel):
    status: str
    completion_details: str | None = Field(default=None, max_length=4000)
    due_at: datetime | None = None


class TaskVerification(BaseModel):
    verified: bool
    notes: str = Field(min_length=3, max_length=2000)


class IncidentResolution(BaseModel):
    resolution_details: str = Field(min_length=10, max_length=4000)


class PredictionFeedbackCreate(BaseModel):
    prediction_id: int
    incident_id: str | None = None
    outcome: str
    feedback_notes: str = Field(min_length=5, max_length=4000)


class WeatherObservationCreate(BaseModel):
    area_id: str
    source: str = Field(min_length=2, max_length=120)
    observed_at: datetime
    rainfall_mm: float | None = Field(default=None, ge=0)
    temperature_c: float | None = None
    humidity_pct: float | None = Field(default=None, ge=0, le=100)
    notes: str | None = Field(default=None, max_length=1000)


class SettingsUpdate(BaseModel):
    working_hours_start: str
    working_hours_end: str
    working_days: list[int] = Field(min_length=1, max_length=7)
    weather_max_age_hours: int = Field(ge=1, le=168)
    routine_acknowledgement_hours: int = Field(ge=1, le=168)
    escalation_level_1_minutes: int = Field(ge=1, le=10080)
    escalation_level_2_minutes: int = Field(ge=1, le=10080)
    escalation_level_3_minutes: int = Field(ge=1, le=10080)


def audit(connection, user_id, action, entity_type, entity_id=None, details=None):
    connection.execute(
        """
        INSERT INTO audit_logs (user_id, action, entity_type, entity_id, details, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            action,
            entity_type,
            str(entity_id) if entity_id is not None else None,
            json.dumps(details or {}, separators=(",", ":")),
            utc_now(),
        ),
    )


def area_by_id(connection, area_id, verified=True, model_ready=False):
    area = connection.execute(
        "SELECT * FROM registered_areas WHERE area_id = ?",
        (area_id,),
    ).fetchone()
    if area is None:
        raise HTTPException(status_code=404, detail="Area not found.")
    if verified and area["status"] != "verified":
        raise HTTPException(
            status_code=422,
            detail="This area is pending verification and cannot receive reports or predictions.",
        )
    if model_ready and not area["model_ready"]:
        raise HTTPException(
            status_code=422,
            detail=(
                "This area is not approved for model predictions. Verify the area, "
                "record at least three valid observations, and confirm model readiness."
            ),
        )
    return area


def department_for_category(connection, category):
    category = category if category in CATEGORIES else "other"
    department = connection.execute(
        """
        SELECT department_id FROM departments
        WHERE category = ? AND is_active = 1
        """,
        (category,),
    ).fetchone()
    if department:
        return department["department_id"]
    fallback = connection.execute(
        """
        SELECT department_id FROM departments
        WHERE department_id = 'municipal' AND is_active = 1
        """
    ).fetchone()
    if fallback:
        return fallback["department_id"]
    raise HTTPException(status_code=503, detail="No responsible department is configured.")


def _settings(connection):
    return {
        row["setting_key"]: row["setting_value"]
        for row in connection.execute(
            "SELECT setting_key, setting_value FROM system_settings"
        )
    }


def _next_routine_time(now, settings):
    local_now = now.astimezone(GOA_TIMEZONE)
    try:
        start = datetime.strptime(
            settings.get("working_hours_start", "09:00"), "%H:%M"
        ).time()
        end = datetime.strptime(
            settings.get("working_hours_end", "17:00"), "%H:%M"
        ).time()
        workdays = {
            int(day)
            for day in settings.get("working_days", "0,1,2,3,4").split(",")
        }
    except (ValueError, TypeError):
        raise HTTPException(status_code=500, detail="Invalid notification schedule configuration.")
    if start >= end or not workdays or any(day < 0 or day > 6 for day in workdays):
        raise HTTPException(status_code=500, detail="Invalid notification schedule configuration.")
    if local_now.weekday() in workdays and start <= local_now.time() < end:
        return now
    for offset in range(8):
        candidate_date = local_now.date() + timedelta(days=offset)
        if candidate_date.weekday() not in workdays:
            continue
        candidate = datetime.combine(candidate_date, start, tzinfo=GOA_TIMEZONE)
        if candidate > local_now:
            return candidate.astimezone(timezone.utc)
    raise HTTPException(status_code=500, detail="No upcoming notification window is configured.")


def _queue_notification(connection, incident_id, department_id, urgency):
    now = datetime.now(timezone.utc)
    settings = _settings(connection)
    scheduled_for = (
        now if urgency == "critical" else _next_routine_time(now, settings)
    )
    status = (
        "internal_queued"
        if urgency == "critical" or scheduled_for <= now
        else "scheduled"
    )
    connection.execute(
        """
        INSERT INTO notifications (
            notification_id, incident_id, department_id, urgency, status,
            scheduled_for, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(incident_id, department_id) DO UPDATE SET
            urgency = CASE
                WHEN excluded.urgency = 'critical' THEN 'critical'
                ELSE notifications.urgency
            END,
            status = CASE
                WHEN excluded.urgency = 'critical'
                     AND notifications.status NOT IN ('acknowledged', 'cancelled')
                    THEN 'internal_queued'
                ELSE notifications.status
            END,
            scheduled_for = CASE
                WHEN excluded.urgency = 'critical'
                     AND notifications.status NOT IN ('acknowledged', 'cancelled')
                    THEN excluded.scheduled_for
                ELSE notifications.scheduled_for
            END
        """,
        (
            str(uuid4()),
            incident_id,
            department_id,
            urgency,
            status,
            scheduled_for.isoformat(timespec="seconds"),
            utc_now(),
        ),
    )


def _create_task(connection, incident_id, department_id, task_details, due_at, created_by):
    task_id = str(uuid4())
    connection.execute(
        """
        INSERT INTO assigned_tasks (
            task_id, incident_id, department_id, task_details, due_at,
            created_by, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            task_id,
            incident_id,
            department_id,
            task_details,
            due_at,
            created_by,
            utc_now(),
            utc_now(),
        ),
    )
    return task_id


def create_high_risk_incident(prediction_id, ward_name, risk_results):
    high_categories = [
        category
        for category, result in risk_results.items()
        if result == "High"
    ]
    if not high_categories:
        return None

    with closing(get_connection()) as connection:
        with connection:
            area = connection.execute(
                "SELECT * FROM registered_areas WHERE area_name = ? COLLATE NOCASE",
                (ward_name,),
            ).fetchone()
            if area is None or area["status"] != "verified":
                return None

            existing = connection.execute(
                """
                SELECT incident_id
                FROM incidents
                WHERE area_id = ?
                  AND issue_category = 'ai_warning'
                  AND status IN ('open', 'acknowledged', 'in_progress', 'verification_required')
                  AND created_at >= ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (
                    area["area_id"],
                    (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(),
                ),
            ).fetchone()

            now = utc_now()
            if existing:
                incident_id = existing["incident_id"]
                for category in high_categories:
                    department_id = department_for_category(connection, category)
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO incident_departments (
                            incident_id, department_id, is_primary
                        )
                        VALUES (?, ?, 0)
                        """,
                        (incident_id, department_id),
                    )
                    _queue_notification(
                        connection, incident_id, department_id, "critical"
                    )
                return incident_id

            primary_department = department_for_category(connection, high_categories[0])
            incident_id = str(uuid4())
            risk_summary = ", ".join(
                f"{category.title()}: High"
                for category in high_categories
            )
            description = (
                "AI-generated early warning only; no service failure is confirmed. "
                f"High-risk model outputs: {risk_summary}."
            )
            due_at = (
                datetime.now(timezone.utc) + timedelta(minutes=30)
            ).isoformat(timespec="seconds")
            connection.execute(
                """
                INSERT INTO incidents (
                    incident_id, area_id, issue_category, description,
                    complaint_source, priority, ai_risk_assessment, prediction_id,
                    primary_department_id, status, due_at, created_at, updated_at
                )
                VALUES (?, ?, 'ai_warning', ?, 'ai_warning', 'critical', ?, ?, ?, 'open', ?, ?, ?)
                """,
                (
                    incident_id,
                    area["area_id"],
                    description,
                    json.dumps(risk_results, separators=(",", ":")),
                    prediction_id,
                    primary_department,
                    due_at,
                    now,
                    now,
                ),
            )
            for category in high_categories:
                department_id = department_for_category(connection, category)
                connection.execute(
                    """
                    INSERT OR IGNORE INTO incident_departments (
                        incident_id, department_id, is_primary
                    )
                    VALUES (?, ?, ?)
                    """,
                    (
                        incident_id,
                        department_id,
                        int(department_id == primary_department),
                    ),
                )
                _queue_notification(
                    connection, incident_id, department_id, "critical"
                )
            connection.execute(
                """
                INSERT INTO alerts (
                    alert_id, incident_id, severity, status, created_at
                )
                VALUES (?, ?, 'critical', 'open', ?)
                """,
                (str(uuid4()), incident_id, now),
            )
            _create_task(
                connection,
                incident_id,
                primary_department,
                "Review the AI early warning and inspect the affected public service.",
                due_at,
                None,
            )
            return incident_id


def _can_access_incident(connection, incident_id, user):
    incident = connection.execute(
        "SELECT * FROM incidents WHERE incident_id = ?",
        (incident_id,),
    ).fetchone()
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    if user["role"] == "administrator":
        return incident
    if user["role"] == "department_official":
        access = connection.execute(
            """
            SELECT 1 FROM incident_departments
            WHERE incident_id = ? AND department_id = ?
            """,
            (incident_id, user["department_id"]),
        ).fetchone()
        if not access:
            raise HTTPException(status_code=403, detail="Incident is outside your department.")
    elif user["role"] == "field_worker":
        access = connection.execute(
            """
            SELECT 1 FROM assigned_tasks
            WHERE incident_id = ? AND assigned_user_id = ?
            """,
            (incident_id, user["user_id"]),
        ).fetchone()
        if not access:
            raise HTTPException(status_code=403, detail="Incident is not assigned to you.")
    elif user["role"] == "citizen":
        access = connection.execute(
            """
            SELECT 1 FROM complaints
            WHERE incident_id = ? AND submitted_by = ?
            """,
            (incident_id, user["user_id"]),
        ).fetchone()
        if not access:
            raise HTTPException(status_code=403, detail="Incident is not linked to your complaint.")
    return incident


def _incident_payload(connection, incident):
    result = dict(incident)
    result["area_name"] = connection.execute(
        "SELECT area_name FROM registered_areas WHERE area_id = ?",
        (incident["area_id"],),
    ).fetchone()["area_name"]
    result["department_name"] = connection.execute(
        "SELECT name FROM departments WHERE department_id = ?",
        (incident["primary_department_id"],),
    ).fetchone()["name"]
    responsible = connection.execute(
        "SELECT display_name FROM users WHERE user_id = ?",
        (incident["responsible_user_id"],),
    ).fetchone()
    result["responsible_user_name"] = (
        responsible["display_name"] if responsible else None
    )
    result["departments"] = [
        dict(row)
        for row in connection.execute(
            """
            SELECT d.department_id, d.name, idp.is_primary,
                   idp.acknowledged_by, idp.acknowledged_at
            FROM incident_departments idp
            JOIN departments d ON d.department_id = idp.department_id
            WHERE idp.incident_id = ?
            ORDER BY idp.is_primary DESC, d.name
            """,
            (incident["incident_id"],),
        )
    ]
    result["complaints"] = [
        dict(row)
        for row in connection.execute(
            """
            SELECT complaint_id, reporter_name, complaint_source, description,
                   duplicate_similarity, submitted_at, submitted_by
            FROM complaints WHERE incident_id = ?
            ORDER BY submitted_at
            """,
            (incident["incident_id"],),
        )
    ]
    result["tasks"] = [
        dict(row)
        for row in connection.execute(
            """
            SELECT t.*, u.display_name AS assigned_user_name
            FROM assigned_tasks t
            LEFT JOIN users u ON u.user_id = t.assigned_user_id
            WHERE t.incident_id = ?
            ORDER BY t.created_at
            """,
            (incident["incident_id"],),
        )
    ]
    result["action_history"] = [
        dict(row)
        for row in connection.execute(
            """
            SELECT wc.*, u.display_name AS submitter_name,
                   verifier.display_name AS verifier_name
            FROM work_completion_records wc
            JOIN users u ON u.user_id = wc.submitted_by
            LEFT JOIN users verifier ON verifier.user_id = wc.verified_by
            JOIN assigned_tasks t ON t.task_id = wc.task_id
            WHERE t.incident_id = ?
            ORDER BY wc.submitted_at
            """,
            (incident["incident_id"],),
        )
    ]
    result["escalation_history"] = [
        dict(row)
        for row in connection.execute(
            """
            SELECT * FROM escalation_history
            WHERE incident_id = ? ORDER BY escalated_at
            """,
            (incident["incident_id"],),
        )
    ]
    return result


def run_scheduled_notifications():
    now = utc_now()
    with closing(get_connection()) as connection:
        with connection:
            connection.execute(
                """
                UPDATE notifications
                SET status = 'internal_queued'
                WHERE status = 'scheduled' AND scheduled_for <= ?
                """,
                (now,),
            )


def run_escalations():
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat(timespec="seconds")
    with closing(get_connection()) as connection:
        with connection:
            settings = _settings(connection)
            deadlines = [
                (1, int(settings.get("escalation_level_1_minutes", "30"))),
                (2, int(settings.get("escalation_level_2_minutes", "120"))),
                (3, int(settings.get("escalation_level_3_minutes", "360"))),
            ]
            incidents = connection.execute(
                """
                SELECT i.*, a.severity
                FROM incidents i
                LEFT JOIN alerts a ON a.incident_id = i.incident_id
                WHERE i.status IN ('open', 'acknowledged', 'in_progress', 'verification_required')
                """
            ).fetchall()
            for incident in incidents:
                age = now_dt - datetime.fromisoformat(incident["created_at"])
                existing_levels = {
                    row["level"]
                    for row in connection.execute(
                        "SELECT level FROM escalation_history WHERE incident_id = ?",
                        (incident["incident_id"],),
                    )
                }
                for level, minutes in deadlines:
                    if level in existing_levels or age < timedelta(minutes=minutes):
                        continue
                    recipient_role = (
                        "assigned_department"
                        if level == 1
                        else "department_supervisor"
                        if level == 2
                        else "system_administrator"
                    )
                    connection.execute(
                        """
                        INSERT INTO escalation_history (
                            escalation_id, incident_id, level, recipient_role,
                            reason, escalated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(uuid4()),
                            incident["incident_id"],
                            level,
                            recipient_role,
                            f"Unresolved incident exceeded level {level} response deadline ({minutes} minutes).",
                            now,
                        ),
                    )
                    for department in connection.execute(
                        "SELECT department_id FROM incident_departments WHERE incident_id = ?",
                        (incident["incident_id"],),
                    ):
                        _queue_notification(
                            connection,
                            incident["incident_id"],
                            department["department_id"],
                            "critical" if incident["severity"] == "critical" else "routine",
                        )
                    break


@router.post("/auth/login")
def login(data: LoginRequest):
    with closing(get_connection()) as connection:
        user = connection.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE AND username != ?",
            (data.username.strip(), DEMO_USERNAME),
        ).fetchone()
    if (
        user is None
        or not user["is_active"]
        or not verify_password(
            data.password,
            user["password_salt"],
            user["password_hash"],
            user["password_iterations"],
        )
    ):
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    return {
        "access_token": create_access_token(user["user_id"]),
        "token_type": "bearer",
        "expires_in": 8 * 60 * 60,
        "user": {
            "user_id": user["user_id"],
            "username": user["username"],
            "display_name": user["display_name"],
            "role": user["role"],
            "department_id": user["department_id"],
        },
    }


@router.get("/auth/me")
def current_user(user=Depends(AUTHENTICATED)):
    return user


@router.get("/users")
def list_users(user=Depends(ADMIN)):
    with closing(get_connection()) as connection:
        return {
            "users": [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT u.user_id, u.username, u.display_name, u.role,
                           u.department_id, d.name AS department_name,
                           u.is_active, u.created_at
                    FROM users u
                    LEFT JOIN departments d ON d.department_id = u.department_id
                    WHERE u.username != ?
                    ORDER BY u.created_at DESC
                    """,
                    (DEMO_USERNAME,),
                )
            ]
        }


@router.get("/users/assignable")
def list_assignable_users(user=Depends(FIELD)):
    query = """
        SELECT user_id, display_name, role, department_id
        FROM users
        WHERE is_active = 1 AND role IN ('department_official', 'field_worker')
    """
    parameters = []
    if user["role"] == "department_official":
        query += " AND department_id = ?"
        parameters.append(user["department_id"])
    query += " ORDER BY display_name"
    with closing(get_connection()) as connection:
        rows = connection.execute(query, parameters).fetchall()
    return {"users": [dict(row) for row in rows]}


@router.post("/users", status_code=201)
def create_user(data: UserCreate, user=Depends(ADMIN)):
    valid_roles = {"administrator", "department_official", "field_worker", "citizen"}
    if data.role not in valid_roles:
        raise HTTPException(status_code=422, detail="Unsupported user role.")
    if data.role in {"department_official", "field_worker"} and not data.department_id:
        raise HTTPException(status_code=422, detail="This role requires a department.")
    if data.role == "administrator" and data.department_id:
        raise HTTPException(status_code=422, detail="Administrators are not department-bound.")
    salt, password_hash, iterations = hash_password(data.password)
    with closing(get_connection()) as connection:
        try:
            with connection:
                if data.department_id and not connection.execute(
                    "SELECT 1 FROM departments WHERE department_id = ? AND is_active = 1",
                    (data.department_id,),
                ).fetchone():
                    raise HTTPException(status_code=422, detail="Department is not registered.")
                cursor = connection.execute(
                    """
                    INSERT INTO users (
                        username, display_name, password_hash, password_salt,
                        password_iterations, role, department_id, created_by, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        data.username.strip(),
                        data.display_name.strip(),
                        password_hash,
                        salt,
                        iterations,
                        data.role,
                        data.department_id,
                        user["user_id"],
                        utc_now(),
                    ),
                )
                user_id = cursor.lastrowid
                audit(connection, user["user_id"], "user.created", "user", user_id, {"role": data.role})
        except sqlite3.IntegrityError as error:
            raise HTTPException(status_code=409, detail="Username already exists.") from error
    return {"user_id": user_id, "username": data.username, "role": data.role}


@router.patch("/users/{user_id}")
def update_user(user_id: int, data: UserUpdate, user=Depends(ADMIN)):
    valid_roles = {"administrator", "department_official", "field_worker", "citizen"}
    if data.role not in valid_roles:
        raise HTTPException(status_code=422, detail="Unsupported user role.")
    if data.role in {"department_official", "field_worker"} and not data.department_id:
        raise HTTPException(status_code=422, detail="This role requires a department.")
    if data.role in {"administrator", "citizen"} and data.department_id:
        raise HTTPException(
            status_code=422,
            detail="Administrators and citizens cannot be department-bound.",
        )
    with closing(get_connection()) as connection:
        try:
            with connection:
                target = connection.execute(
                    "SELECT * FROM users WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
                if target is None:
                    raise HTTPException(status_code=404, detail="User not found.")
                if user_id == user["user_id"] and (
                    not data.is_active or data.role != "administrator"
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="You cannot deactivate or demote your own administrator account.",
                    )
                if target["role"] == "administrator" and target["is_active"] and (
                    not data.is_active or data.role != "administrator"
                ):
                    other_admin = connection.execute(
                        """
                        SELECT 1 FROM users
                        WHERE role='administrator' AND is_active=1 AND user_id != ?
                        LIMIT 1
                        """,
                        (user_id,),
                    ).fetchone()
                    if not other_admin:
                        raise HTTPException(
                            status_code=409,
                            detail="The last active administrator cannot be removed.",
                        )
                if data.department_id and not connection.execute(
                    "SELECT 1 FROM departments WHERE department_id=? AND is_active=1",
                    (data.department_id,),
                ).fetchone():
                    raise HTTPException(status_code=422, detail="Department is not registered.")
                if (
                    target["role"] == "field_worker"
                    and data.role != "field_worker"
                ) or not data.is_active:
                    active_tasks = connection.execute(
                        """
                        SELECT 1 FROM assigned_tasks
                        WHERE assigned_user_id=? AND status != 'verified'
                        LIMIT 1
                        """,
                        (user_id,),
                    ).fetchone()
                    if active_tasks:
                        raise HTTPException(
                            status_code=409,
                            detail="Reassign or verify the user's active tasks before changing or deactivating this account.",
                        )
                connection.execute(
                    """
                    UPDATE users
                    SET display_name=?, role=?, department_id=?, is_active=?
                    WHERE user_id=?
                    """,
                    (
                        data.display_name.strip(),
                        data.role,
                        data.department_id,
                        int(data.is_active),
                        user_id,
                    ),
                )
                audit(
                    connection,
                    user["user_id"],
                    "user.updated",
                    "user",
                    user_id,
                    {
                        "role": data.role,
                        "department_id": data.department_id,
                        "is_active": data.is_active,
                    },
                )
        except sqlite3.IntegrityError as error:
            raise HTTPException(status_code=409, detail="User update violates account constraints.") from error
    return {
        "user_id": user_id,
        "display_name": data.display_name.strip(),
        "role": data.role,
        "department_id": data.department_id,
        "is_active": data.is_active,
    }


@router.get("/areas")
def list_areas(user=Depends(AUTHENTICATED)):
    area_filter = " WHERE a.status = 'verified'" if user["role"] == "citizen" else ""
    with closing(get_connection()) as connection:
        rows = connection.execute(
            f"""
            SELECT a.*, creator.display_name AS created_by_name,
                   verifier.display_name AS verified_by_name
            FROM registered_areas a
            LEFT JOIN users creator ON creator.user_id = a.created_by
            LEFT JOIN users verifier ON verifier.user_id = a.verified_by
            {area_filter}
            ORDER BY a.area_name
            """
        ).fetchall()
    return {"areas": [dict(row) for row in rows]}


@router.post("/areas", status_code=201)
def register_area(data: AreaCreate, user=Depends(ADMIN)):
    area_id = str(uuid4())
    with closing(get_connection()) as connection:
        try:
            with connection:
                connection.execute(
                    """
                    INSERT INTO registered_areas (
                        area_id, area_name, ward_code, status, model_ready,
                        valid_data_points, created_by, created_at
                    )
                    VALUES (?, ?, ?, 'pending', 0, 0, ?, ?)
                    """,
                    (
                        area_id,
                        data.area_name.strip(),
                        data.ward_code.strip() if data.ward_code else None,
                        user["user_id"],
                        utc_now(),
                    ),
                )
                audit(connection, user["user_id"], "area.registered", "area", area_id)
        except sqlite3.IntegrityError as error:
            raise HTTPException(status_code=409, detail="Area name or ward code already exists.") from error
    return {"area_id": area_id, "area_name": data.area_name.strip(), "status": "pending"}


@router.put("/areas/{area_id}/verification")
def verify_area(area_id: str, data: AreaVerification, user=Depends(ADMIN)):
    with closing(get_connection()) as connection:
        with connection:
            area = area_by_id(connection, area_id, verified=False)
            valid_data_points = connection.execute(
                """
                SELECT COUNT(*) FROM area_data_observations
                WHERE area_id = ?
                """,
                (area_id,),
            ).fetchone()[0]
            if data.verified and (valid_data_points < 3 or not data.model_ready):
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Verification for predictions requires at least three "
                        "recorded valid observations and explicit model readiness."
                    ),
                )
            ready = int(data.verified and data.model_ready and valid_data_points >= 3)
            connection.execute(
                """
                UPDATE registered_areas
                SET status = ?, model_ready = ?, valid_data_points = ?,
                    verified_by = ?, verified_at = ?
                WHERE area_id = ?
                """,
                (
                    "verified" if data.verified else "pending",
                    int(ready),
                    valid_data_points,
                    user["user_id"] if data.verified else None,
                    utc_now() if data.verified else None,
                    area_id,
                ),
            )
            audit(
                connection,
                user["user_id"],
                "area.verification_changed",
                "area",
                area_id,
                {**data.model_dump(), "valid_data_points": valid_data_points},
            )
    return {
        "area_id": area_id,
        "status": "verified" if data.verified else "pending",
        "model_ready": bool(ready),
        "valid_data_points": valid_data_points,
    }


@router.post("/areas/{area_id}/observations", status_code=201)
def record_area_observation(
    area_id: str,
    data: AreaDataObservation,
    user=Depends(ADMIN),
):
    if data.observed_at.tzinfo is None:
        raise HTTPException(
            status_code=422,
            detail="Observation timestamp must include a timezone.",
        )
    observed_at = data.observed_at.astimezone(timezone.utc)
    if observed_at > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise HTTPException(status_code=422, detail="Observation time cannot be in the future.")
    observation_id = str(uuid4())
    model_data = data.model_dump(exclude={"source", "observed_at"})
    with closing(get_connection()) as connection:
        try:
            with connection:
                area_by_id(connection, area_id, verified=False)
                connection.execute(
                    """
                    INSERT INTO area_data_observations (
                        observation_id, area_id, source, observed_at, data_json,
                        recorded_by, recorded_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        observation_id,
                        area_id,
                        data.source.strip(),
                        observed_at.isoformat(),
                        json.dumps(model_data, separators=(",", ":")),
                        user["user_id"],
                        utc_now(),
                    ),
                )
                valid_data_points = connection.execute(
                    "SELECT COUNT(*) FROM area_data_observations WHERE area_id = ?",
                    (area_id,),
                ).fetchone()[0]
                connection.execute(
                    """
                    UPDATE registered_areas SET valid_data_points = ?
                    WHERE area_id = ?
                    """,
                    (valid_data_points, area_id),
                )
                audit(
                    connection,
                    user["user_id"],
                    "area.observation_recorded",
                    "area_data_observation",
                    observation_id,
                    {"area_id": area_id, "source": data.source},
                )
        except sqlite3.IntegrityError as error:
            raise HTTPException(
                status_code=409,
                detail="An observation for this area and timestamp already exists.",
            ) from error
    return {
        "observation_id": observation_id,
        "valid_data_points": valid_data_points,
    }


@router.put("/areas/{area_id}")
def correct_area(area_id: str, data: AreaCorrection, user=Depends(ADMIN)):
    with closing(get_connection()) as connection:
        try:
            with connection:
                area = area_by_id(connection, area_id, verified=False)
                new_name = data.area_name.strip()
                new_code = data.ward_code.strip() if data.ward_code else None
                connection.execute(
                    """
                    INSERT INTO area_corrections (
                        correction_id, area_id, previous_name, corrected_name,
                        previous_ward_code, corrected_ward_code, correction_reason,
                        corrected_by, corrected_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()), area_id, area["area_name"], new_name,
                        area["ward_code"], new_code, data.reason,
                        user["user_id"], utc_now(),
                    ),
                )
                connection.execute(
                    "UPDATE registered_areas SET area_name = ?, ward_code = ? WHERE area_id = ?",
                    (new_name, new_code, area_id),
                )
                audit(connection, user["user_id"], "area.corrected", "area", area_id, data.model_dump())
        except sqlite3.IntegrityError as error:
            raise HTTPException(status_code=409, detail="Area name or ward code already exists.") from error
    return {"area_id": area_id, "area_name": new_name, "ward_code": new_code}


@router.get("/areas/{area_id}/corrections")
def list_area_corrections(area_id: str, user=Depends(ADMIN)):
    with closing(get_connection()) as connection:
        area_by_id(connection, area_id, verified=False)
        rows = connection.execute(
            """
            SELECT c.*, u.display_name AS corrected_by_name
            FROM area_corrections c
            JOIN users u ON u.user_id = c.corrected_by
            WHERE c.area_id = ? ORDER BY c.corrected_at DESC
            """,
            (area_id,),
        ).fetchall()
    return {"corrections": [dict(row) for row in rows]}


@router.get("/departments")
def list_departments(user=Depends(AUTHENTICATED)):
    with closing(get_connection()) as connection:
        rows = connection.execute(
            "SELECT * FROM departments ORDER BY name"
        ).fetchall()
    return {"departments": [dict(row) for row in rows]}


@router.post("/departments", status_code=201)
def create_department(data: DepartmentCreate, user=Depends(ADMIN)):
    with closing(get_connection()) as connection:
        try:
            with connection:
                connection.execute(
                    """
                    INSERT INTO departments (department_id, name, category, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (data.department_id, data.name.strip(), data.category, utc_now()),
                )
                audit(connection, user["user_id"], "department.created", "department", data.department_id)
        except sqlite3.IntegrityError as error:
            raise HTTPException(status_code=409, detail="Department ID, name, or category already exists.") from error
    return {"department_id": data.department_id, "name": data.name}


@router.patch("/departments/{department_id}")
def update_department(
    department_id: str,
    data: DepartmentUpdate,
    user=Depends(ADMIN),
):
    with closing(get_connection()) as connection:
        with connection:
            department = connection.execute(
                "SELECT * FROM departments WHERE department_id=?",
                (department_id,),
            ).fetchone()
            if department is None:
                raise HTTPException(status_code=404, detail="Department not found.")
            if department["is_active"] and not data.is_active:
                active_incident = connection.execute(
                    """
                    SELECT 1 FROM incident_departments idp
                    JOIN incidents i ON i.incident_id=idp.incident_id
                    WHERE idp.department_id=?
                      AND i.status NOT IN ('resolved', 'closed')
                    LIMIT 1
                    """,
                    (department_id,),
                ).fetchone()
                if active_incident:
                    raise HTTPException(
                        status_code=409,
                        detail="Resolve or reassign this department's active incidents before deactivation.",
                    )
            try:
                connection.execute(
                    "UPDATE departments SET name=?, is_active=? WHERE department_id=?",
                    (data.name.strip(), int(data.is_active), department_id),
                )
            except sqlite3.IntegrityError as error:
                raise HTTPException(status_code=409, detail="Department name already exists.") from error
            audit(
                connection,
                user["user_id"],
                "department.updated",
                "department",
                department_id,
                {"name": data.name.strip(), "is_active": data.is_active},
            )
    return {
        "department_id": department_id,
        "name": data.name.strip(),
        "is_active": data.is_active,
    }


def _description_similarity(left, right):
    normalized_left = " ".join(left.lower().split())
    normalized_right = " ".join(right.lower().split())
    return SequenceMatcher(None, normalized_left, normalized_right).ratio()


def _create_complaint(data, reporter, source, submitted_by):
    if data.issue_category not in CATEGORIES:
        raise HTTPException(status_code=422, detail="Unsupported complaint category.")
    if data.priority not in {"low", "medium", "high", "critical"}:
        raise HTTPException(status_code=422, detail="Unsupported priority.")
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat(timespec="microseconds")
    complaint_id = str(uuid4())
    threshold = now_dt - timedelta(hours=48)

    with closing(get_connection()) as connection:
        with connection:
            area = area_by_id(connection, data.area_id)
            candidates = connection.execute(
                """
                SELECT i.incident_id, i.description, i.report_count, i.priority
                FROM incidents i
                WHERE i.area_id = ? AND i.issue_category = ?
                  AND i.complaint_source != 'ai_warning'
                  AND i.status IN ('open', 'acknowledged', 'in_progress', 'verification_required')
                  AND i.created_at >= ?
                ORDER BY i.created_at DESC
                """,
                (data.area_id, data.issue_category, threshold.isoformat()),
            ).fetchall()
            duplicate = None
            similarity = 0.0
            for candidate in candidates:
                candidate_similarity = _description_similarity(
                    data.description, candidate["description"]
                )
                if candidate_similarity >= 0.72:
                    duplicate = candidate
                    similarity = candidate_similarity
                    break

            department_id = department_for_category(connection, data.issue_category)
            if duplicate:
                incident_id = duplicate["incident_id"]
                connection.execute(
                    """
                    UPDATE incidents
                    SET report_count = report_count + 1,
                        priority = CASE
                            WHEN priority = 'critical' OR ? = 'critical' THEN 'critical'
                            WHEN priority = 'high' OR ? = 'high' THEN 'high'
                            WHEN priority = 'medium' OR ? = 'medium' THEN 'medium'
                            ELSE 'low'
                        END,
                        updated_at = ?
                    WHERE incident_id = ?
                    """,
                    (data.priority, data.priority, data.priority, now, incident_id),
                )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO incident_departments (
                        incident_id, department_id, is_primary
                    )
                    VALUES (?, ?, 0)
                    """,
                    (incident_id, department_id),
                )
            else:
                incident_id = str(uuid4())
                settings = _settings(connection)
                due_at = (
                    now_dt + timedelta(
                        hours=int(settings.get("routine_acknowledgement_hours", "4"))
                    )
                ).isoformat(timespec="seconds")
                connection.execute(
                    """
                    INSERT INTO incidents (
                        incident_id, area_id, issue_category, description,
                        complaint_source, priority, primary_department_id, status,
                        report_count, due_at, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'open', 1, ?, ?, ?)
                    """,
                    (
                        incident_id, data.area_id, data.issue_category,
                        data.description.strip(), source, data.priority,
                        department_id, due_at, now, now,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO incident_departments (
                        incident_id, department_id, is_primary
                    )
                    VALUES (?, ?, 1)
                    """,
                    (incident_id, department_id),
                )
                _create_task(
                    connection, incident_id, department_id,
                    f"Investigate and respond to reported {data.issue_category} issue.",
                    due_at, submitted_by,
                )

            connection.execute(
                """
                INSERT INTO complaints (
                    complaint_id, incident_id, reporter_name, reporter_contact,
                    complaint_source, description, submitted_by,
                    duplicate_similarity, submitted_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    complaint_id, incident_id, reporter, data.reporter_contact,
                    source, data.description.strip(), submitted_by,
                    similarity if duplicate else None, now,
                ),
            )
            incident = connection.execute(
                "SELECT priority FROM incidents WHERE incident_id = ?",
                (incident_id,),
            ).fetchone()
            if incident["priority"] in {"high", "critical"}:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO alerts (
                        alert_id, incident_id, severity, status, created_at
                    )
                    VALUES (?, ?, ?, 'open', ?)
                    """,
                    (
                        str(uuid4()), incident_id,
                        "critical" if incident["priority"] == "critical" else "high",
                        now,
                    ),
                )
                _queue_notification(
                    connection, incident_id, department_id,
                    "critical" if incident["priority"] == "critical" else "routine",
                )
            else:
                _queue_notification(connection, incident_id, department_id, "routine")
            audit(
                connection,
                submitted_by,
                "complaint.registered",
                "complaint",
                complaint_id,
                {
                    "incident_id": incident_id,
                    "area_id": area["area_id"],
                    "duplicate_grouped": bool(duplicate),
                    "source": source,
                },
            )
    return {
        "complaint_id": complaint_id,
        "incident_id": incident_id,
        "area_name": area["area_name"],
        "submitted_at": now,
        "duplicate_grouped": bool(duplicate),
        "similarity": round(similarity, 3) if duplicate else None,
        "report_count": duplicate["report_count"] + 1 if duplicate else 1,
        "acknowledgement": (
            "Complaint received and grouped with an existing incident for review."
            if duplicate
            else "Complaint received. The incident is pending official review."
        ),
    }


@router.post("/complaints", status_code=201)
def create_citizen_complaint(
    data: ComplaintCreate,
    user=Depends(require_roles("citizen")),
):
    return _create_complaint(
        data,
        data.reporter_name.strip() if DEMO_MODE else user["display_name"],
        "citizen",
        user["user_id"],
    )


@router.post("/complaints/register-on-behalf", status_code=201)
def register_complaint_on_behalf(
    data: ComplaintCreate,
    user=Depends(require_roles("administrator", "department_official", "field_worker")),
):
    return _create_complaint(
        data,
        data.reporter_name.strip(),
        user["role"] if user["role"] in {"field_worker"} else "municipal_staff",
        user["user_id"],
    )


@router.get("/complaints")
def list_complaints(user=Depends(AUTHENTICATED)):
    query = """
        SELECT c.*, i.area_id, a.area_name, i.issue_category,
               i.priority, i.status AS incident_status, i.report_count
        FROM complaints c
        JOIN incidents i ON i.incident_id = c.incident_id
        JOIN registered_areas a ON a.area_id = i.area_id
    """
    parameters = []
    if user["role"] == "citizen":
        query += " WHERE c.submitted_by = ?"
        parameters.append(user["user_id"])
    elif user["role"] == "department_official":
        query += """
            WHERE EXISTS (
                SELECT 1 FROM incident_departments idp
                WHERE idp.incident_id = i.incident_id AND idp.department_id = ?
            )
        """
        parameters.append(user["department_id"])
    elif user["role"] == "field_worker":
        query += """
            WHERE EXISTS (
                SELECT 1 FROM assigned_tasks t
                WHERE t.incident_id = i.incident_id AND t.assigned_user_id = ?
            )
        """
        parameters.append(user["user_id"])
    query += " ORDER BY c.submitted_at DESC"
    with closing(get_connection()) as connection:
        rows = connection.execute(query, parameters).fetchall()
    return {"complaints": [dict(row) for row in rows]}


@router.get("/incidents/summary")
def incidents_summary(user=Depends(FIELD)):
    base_filter = ""
    parameters = []
    if user["role"] == "department_official":
        base_filter = """
            AND EXISTS (
                SELECT 1 FROM incident_departments idp
                WHERE idp.incident_id = i.incident_id AND idp.department_id = ?
            )
        """
        parameters.append(user["department_id"])
    elif user["role"] == "field_worker":
        base_filter = """
            AND EXISTS (
                SELECT 1 FROM assigned_tasks t
                WHERE t.incident_id = i.incident_id AND t.assigned_user_id = ?
            )
        """
        parameters.append(user["user_id"])
    with closing(get_connection()) as connection:
        counts = connection.execute(
            f"""
            SELECT
                (SELECT COUNT(*) FROM complaints c JOIN incidents ci ON ci.incident_id=c.incident_id
                 WHERE 1=1 {base_filter.replace('i.', 'ci.')}) AS reported_complaints,
                SUM(CASE WHEN i.status IN ('open','acknowledged','in_progress','verification_required') THEN 1 ELSE 0 END) AS open_incidents,
                SUM(CASE WHEN i.priority IN ('high','critical') AND i.status NOT IN ('resolved','closed') THEN 1 ELSE 0 END) AS high_priority_unresolved,
                SUM(CASE WHEN EXISTS (SELECT 1 FROM assigned_tasks t WHERE t.incident_id=i.incident_id AND t.status='verification_required') THEN 1 ELSE 0 END) AS tasks_awaiting_verification,
                SUM(CASE WHEN i.due_at < ? AND i.status NOT IN ('resolved','closed') THEN 1 ELSE 0 END) AS overdue_actions,
                SUM(CASE WHEN EXISTS (SELECT 1 FROM escalation_history e WHERE e.incident_id=i.incident_id) THEN 1 ELSE 0 END) AS escalated_incidents
            FROM incidents i WHERE 1=1 {base_filter}
            """,
            [*parameters, utc_now(), *parameters],
        ).fetchone()
        department_query = """
            SELECT d.department_id, d.name, COUNT(DISTINCT i.incident_id) AS assigned_incidents
            FROM departments d
            LEFT JOIN incident_departments idp ON idp.department_id=d.department_id
            LEFT JOIN incidents i ON i.incident_id=idp.incident_id
            WHERE d.is_active=1
        """
        department_parameters = []
        if user["role"] == "department_official":
            department_query += " AND d.department_id=?"
            department_parameters.append(user["department_id"])
        elif user["role"] == "field_worker":
            department_query += """
                AND EXISTS (
                    SELECT 1 FROM assigned_tasks t
                    WHERE t.department_id=d.department_id AND t.assigned_user_id=?
                )
            """
            department_parameters.append(user["user_id"])
        department_query += " GROUP BY d.department_id ORDER BY d.name"
        department_rows = connection.execute(
            department_query, department_parameters
        ).fetchall()
        recent = connection.execute(
            f"""
            SELECT i.incident_id, a.area_name, i.issue_category, i.resolved_at,
                   i.resolution_details
            FROM incidents i JOIN registered_areas a ON a.area_id=i.area_id
            WHERE i.status='resolved' {base_filter}
            ORDER BY i.resolved_at DESC LIMIT 10
            """,
            parameters,
        ).fetchall()
    return {
        **{key: counts[key] or 0 for key in counts.keys()},
        "department_assigned_incidents": [dict(row) for row in department_rows],
        "recently_resolved": [dict(row) for row in recent],
    }


@router.get("/incidents")
def list_incidents(
    area_id: str | None = None,
    department_id: str | None = None,
    issue_category: str | None = None,
    priority: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    user=Depends(FIELD),
):
    query = """
        SELECT i.*, a.area_name, d.name AS department_name,
               (SELECT COUNT(*) FROM complaints c WHERE c.incident_id=i.incident_id) AS complaints_count,
               EXISTS (SELECT 1 FROM escalation_history e WHERE e.incident_id=i.incident_id) AS is_escalated
        FROM incidents i
        JOIN registered_areas a ON a.area_id=i.area_id
        JOIN departments d ON d.department_id=i.primary_department_id
        WHERE 1=1
    """
    parameters = []
    if user["role"] == "department_official":
        query += """
            AND EXISTS (SELECT 1 FROM incident_departments idp
                        WHERE idp.incident_id=i.incident_id AND idp.department_id=?)
        """
        parameters.append(user["department_id"])
    elif user["role"] == "field_worker":
        query += """
            AND EXISTS (SELECT 1 FROM assigned_tasks t
                        WHERE t.incident_id=i.incident_id AND t.assigned_user_id=?)
        """
        parameters.append(user["user_id"])
    filters = [
        (area_id, "i.area_id = ?"),
        (department_id, "EXISTS (SELECT 1 FROM incident_departments idp WHERE idp.incident_id=i.incident_id AND idp.department_id=?)"),
        (issue_category, "i.issue_category = ?"),
        (priority, "i.priority = ?"),
        (status, "i.status = ?"),
        (date_from, "i.created_at >= ?"),
        (date_to, "i.created_at <= ?"),
    ]
    for value, clause in filters:
        if value is not None:
            query += f" AND {clause}"
            parameters.append(value)
    query += " ORDER BY i.created_at DESC"
    with closing(get_connection()) as connection:
        rows = connection.execute(query, parameters).fetchall()
    return {"incidents": [dict(row) for row in rows], "total_records": len(rows)}


@router.get("/incidents/{incident_id}")
def get_incident(incident_id: str, user=Depends(AUTHENTICATED)):
    with closing(get_connection()) as connection:
        incident = _can_access_incident(connection, incident_id, user)
        result = _incident_payload(connection, incident)
    if user["role"] == "citizen":
        result["complaints"] = [
            {key: value for key, value in complaint.items() if key != "submitted_by"}
            for complaint in result["complaints"]
            if complaint["submitted_by"] == user["user_id"]
        ]
        result["tasks"] = [
            {
                key: task[key]
                for key in ("status", "due_at", "updated_at")
            }
            for task in result["tasks"]
        ]
        result["action_history"] = [
            {
                key: action[key]
                for key in (
                    "completion_status",
                    "completion_details",
                    "submitted_at",
                    "verification_notes",
                    "verified_at",
                )
            }
            for action in result["action_history"]
        ]
    else:
        result["complaints"] = [
            {key: value for key, value in complaint.items() if key != "submitted_by"}
            for complaint in result["complaints"]
        ]
    return result


@router.post("/incidents/{incident_id}/departments")
def add_supporting_departments(
    incident_id: str,
    data: SupportingDepartments,
    user=Depends(STAFF),
):
    with closing(get_connection()) as connection:
        with connection:
            incident = _can_access_incident(connection, incident_id, user)
            if user["role"] == "department_official" and incident["primary_department_id"] != user["department_id"]:
                raise HTTPException(status_code=403, detail="Only the primary department can add supporting departments.")
            for department_id in set(data.department_ids):
                if not connection.execute(
                    "SELECT 1 FROM departments WHERE department_id=? AND is_active=1",
                    (department_id,),
                ).fetchone():
                    raise HTTPException(status_code=422, detail="A selected department is not registered.")
                connection.execute(
                    """
                    INSERT OR IGNORE INTO incident_departments (
                        incident_id, department_id, is_primary
                    )
                    VALUES (?, ?, 0)
                    """,
                    (incident_id, department_id),
                )
                _queue_notification(
                    connection,
                    incident_id,
                    department_id,
                    "critical" if incident["priority"] == "critical" else "routine",
                )
            audit(connection, user["user_id"], "incident.supporting_departments_added", "incident", incident_id, {"departments": list(set(data.department_ids))})
    return {"incident_id": incident_id, "supporting_departments": list(set(data.department_ids))}


@router.post("/incidents/{incident_id}/assign")
def assign_incident(
    incident_id: str,
    data: IncidentAssignment,
    user=Depends(STAFF),
):
    due_at = (data.due_at or datetime.now(timezone.utc) + timedelta(hours=4)).astimezone(timezone.utc).isoformat()
    with closing(get_connection()) as connection:
        with connection:
            incident = _can_access_incident(connection, incident_id, user)
            if user["role"] == "department_official" and user["department_id"] != data.department_id:
                raise HTTPException(status_code=403, detail="You can assign work only within your department.")
            if not connection.execute(
                "SELECT 1 FROM departments WHERE department_id=? AND is_active=1",
                (data.department_id,),
            ).fetchone():
                raise HTTPException(status_code=422, detail="Department is not registered.")
            if data.responsible_user_id and not connection.execute(
                """
                SELECT 1 FROM users
                WHERE user_id=? AND department_id=? AND role IN ('field_worker','department_official')
                  AND is_active=1
                """,
                (data.responsible_user_id, data.department_id),
            ).fetchone():
                raise HTTPException(status_code=422, detail="Responsible user is not active in the selected department.")
            connection.execute(
                """
                INSERT OR IGNORE INTO incident_departments (incident_id, department_id, is_primary)
                VALUES (?, ?, ?)
                """,
                (incident_id, data.department_id, int(data.department_id == incident["primary_department_id"])),
            )
            task_id = _create_task(
                connection, incident_id, data.department_id, data.task_details,
                due_at, user["user_id"]
            )
            connection.execute(
                """
                UPDATE assigned_tasks
                SET assigned_user_id=?, updated_by=?, updated_at=?
                WHERE task_id=?
                """,
                (data.responsible_user_id, user["user_id"], utc_now(), task_id),
            )
            connection.execute(
                """
                UPDATE incidents SET responsible_user_id=?, status='acknowledged',
                    updated_at=? WHERE incident_id=?
                """,
                (data.responsible_user_id, utc_now(), incident_id),
            )
            _queue_notification(
                connection,
                incident_id,
                data.department_id,
                "critical" if incident["priority"] == "critical" else "routine",
            )
            audit(connection, user["user_id"], "incident.assigned", "incident", incident_id, {"task_id": task_id, "department_id": data.department_id})
    return {"incident_id": incident_id, "task_id": task_id, "due_at": due_at}


@router.post("/incidents/{incident_id}/acknowledge")
def acknowledge_incident(incident_id: str, user=Depends(STAFF)):
    with closing(get_connection()) as connection:
        with connection:
            incident = _can_access_incident(connection, incident_id, user)
            connection.execute(
                "UPDATE incidents SET status='acknowledged', updated_at=? WHERE incident_id=?",
                (utc_now(), incident_id),
            )
            connection.execute(
                """
                UPDATE incident_departments
                SET acknowledged_by=?, acknowledged_at=?
                WHERE incident_id=? AND department_id=?
                """,
                (user["user_id"], utc_now(), incident_id, user["department_id"] or incident["primary_department_id"]),
            )
            connection.execute(
                """
                UPDATE notifications
                SET status='acknowledged', acknowledged_by=?, acknowledged_at=?
                WHERE incident_id=? AND department_id=? AND status IN ('internal_queued','scheduled')
                """,
                (user["user_id"], utc_now(), incident_id, user["department_id"] or incident["primary_department_id"]),
            )
            connection.execute(
                "UPDATE alerts SET status='acknowledged', acknowledged_by=?, acknowledged_at=? WHERE incident_id=?",
                (user["user_id"], utc_now(), incident_id),
            )
            audit(connection, user["user_id"], "incident.acknowledged", "incident", incident_id)
    return {"incident_id": incident_id, "status": "acknowledged"}


@router.post("/incidents/{incident_id}/resolve")
def resolve_incident(incident_id: str, data: IncidentResolution, user=Depends(STAFF)):
    with closing(get_connection()) as connection:
        with connection:
            _can_access_incident(connection, incident_id, user)
            if user["role"] == "department_official":
                unverified = connection.execute(
                    """
                    SELECT 1 FROM assigned_tasks
                    WHERE incident_id=? AND department_id=? AND status != 'verified'
                    LIMIT 1
                    """,
                    (incident_id, user["department_id"]),
                ).fetchone()
                if unverified:
                    raise HTTPException(status_code=409, detail="All department tasks must be supervisor-verified before resolution.")
            connection.execute(
                """
                UPDATE incidents
                SET status='resolved', resolution_details=?, resolved_at=?, updated_at=?
                WHERE incident_id=?
                """,
                (data.resolution_details, utc_now(), utc_now(), incident_id),
            )
            connection.execute(
                "UPDATE alerts SET status='resolved', resolved_at=? WHERE incident_id=?",
                (utc_now(), incident_id),
            )
            connection.execute(
                "UPDATE notifications SET status='cancelled' WHERE incident_id=? AND status='scheduled'",
                (incident_id,),
            )
            audit(connection, user["user_id"], "incident.resolved", "incident", incident_id)
    return {"incident_id": incident_id, "status": "resolved"}


@router.get("/tasks")
def list_tasks(
    status: str | None = None,
    user=Depends(FIELD),
):
    query = """
        SELECT t.*, i.priority, i.issue_category, i.status AS incident_status,
               CASE WHEN t.due_at < ? AND t.status != 'verified'
                         AND i.status NOT IN ('resolved', 'closed')
                    THEN 1 ELSE 0 END AS overdue,
               a.area_name, d.name AS department_name, assigned.display_name AS assignee_name
        FROM assigned_tasks t
        JOIN incidents i ON i.incident_id=t.incident_id
        JOIN registered_areas a ON a.area_id=i.area_id
        JOIN departments d ON d.department_id=t.department_id
        LEFT JOIN users assigned ON assigned.user_id=t.assigned_user_id
        WHERE 1=1
    """
    params = [utc_now()]
    if user["role"] == "field_worker":
        query += " AND t.assigned_user_id=?"
        params.append(user["user_id"])
    elif user["role"] == "department_official":
        query += " AND t.department_id=?"
        params.append(user["department_id"])
    if status:
        query += " AND t.status=?"
        params.append(status)
    query += " ORDER BY (t.due_at < ?) DESC, t.due_at ASC"
    params.append(utc_now())
    with closing(get_connection()) as connection:
        rows = connection.execute(query, params).fetchall()
    return {"tasks": [dict(row) for row in rows], "total_records": len(rows)}


@router.patch("/tasks/{task_id}")
def update_task(task_id: str, data: TaskUpdate, user=Depends(FIELD)):
    if data.status not in {"pending", "in_progress", "completed"}:
        raise HTTPException(status_code=422, detail="Workers can set pending, in progress, or completed.")
    if data.status == "completed" and (
        not data.completion_details or len(data.completion_details.strip()) < 10
    ):
        raise HTTPException(status_code=422, detail="Completion details of at least 10 characters are required.")
    with closing(get_connection()) as connection:
        with connection:
            task = connection.execute(
                "SELECT * FROM assigned_tasks WHERE task_id=?",
                (task_id,),
            ).fetchone()
            if task is None:
                raise HTTPException(status_code=404, detail="Task not found.")
            if user["role"] == "field_worker" and task["assigned_user_id"] != user["user_id"]:
                raise HTTPException(status_code=403, detail="This task is not assigned to you.")
            if user["role"] == "department_official" and task["department_id"] != user["department_id"]:
                raise HTTPException(status_code=403, detail="This task is outside your department.")
            new_status = "verification_required" if data.status == "completed" else data.status
            connection.execute(
                """
                UPDATE assigned_tasks
                SET status=?, due_at=COALESCE(?, due_at), updated_by=?, updated_at=?
                WHERE task_id=?
                """,
                (
                    new_status,
                    data.due_at.astimezone(timezone.utc).isoformat() if data.due_at else None,
                    user["user_id"],
                    utc_now(),
                    task_id,
                ),
            )
            connection.execute(
                "UPDATE incidents SET status=?, updated_at=? WHERE incident_id=? AND status NOT IN ('resolved','closed')",
                (
                    "verification_required" if new_status == "verification_required" else "in_progress",
                    utc_now(),
                    task["incident_id"],
                ),
            )
            if new_status == "verification_required":
                connection.execute(
                    """
                    INSERT INTO work_completion_records (
                        completion_id, task_id, submitted_by, completion_details,
                        submitted_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()), task_id, user["user_id"],
                        data.completion_details.strip(), utc_now(),
                    ),
                )
            audit(connection, user["user_id"], "task.updated", "task", task_id, {"status": new_status})
    return {"task_id": task_id, "status": new_status}


@router.post("/tasks/{task_id}/verify")
def verify_task(task_id: str, data: TaskVerification, user=Depends(STAFF)):
    with closing(get_connection()) as connection:
        with connection:
            task = connection.execute(
                "SELECT * FROM assigned_tasks WHERE task_id=?",
                (task_id,),
            ).fetchone()
            if task is None:
                raise HTTPException(status_code=404, detail="Task not found.")
            if user["role"] == "department_official" and task["department_id"] != user["department_id"]:
                raise HTTPException(status_code=403, detail="This task is outside your department.")
            completion = connection.execute(
                """
                SELECT * FROM work_completion_records
                WHERE task_id=? AND completion_status='verification_required'
                ORDER BY submitted_at DESC LIMIT 1
                """,
                (task_id,),
            ).fetchone()
            if completion is None:
                raise HTTPException(status_code=409, detail="No completion is awaiting verification.")
            now = utc_now()
            connection.execute(
                """
                UPDATE work_completion_records
                SET completion_status=?, verified_by=?, verification_notes=?, verified_at=?
                WHERE completion_id=?
                """,
                (
                    "verified" if data.verified else "rejected",
                    user["user_id"],
                    data.notes,
                    now,
                    completion["completion_id"],
                ),
            )
            status = "verified" if data.verified else "pending"
            connection.execute(
                """
                UPDATE assigned_tasks SET status=?, updated_by=?, updated_at=?
                WHERE task_id=?
                """,
                (status, user["user_id"], now, task_id),
            )
            connection.execute(
                """
                UPDATE incidents SET status=?, updated_at=?
                WHERE incident_id=? AND status NOT IN ('resolved','closed')
                """,
                ("in_progress" if data.verified else "open", now, task["incident_id"]),
            )
            audit(connection, user["user_id"], "task.verification_recorded", "task", task_id, {"verified": data.verified, "notes": data.notes})
    return {"task_id": task_id, "status": status, "verified": data.verified}


@router.get("/alerts")
def list_alerts(user=Depends(FIELD)):
    query = """
        SELECT al.*, i.area_id, a.area_name, i.issue_category, i.priority,
               i.status AS incident_status, d.name AS department_name,
               i.due_at,
               EXISTS (SELECT 1 FROM escalation_history e WHERE e.incident_id=i.incident_id) AS escalated
        FROM alerts al
        JOIN incidents i ON i.incident_id=al.incident_id
        JOIN registered_areas a ON a.area_id=i.area_id
        JOIN departments d ON d.department_id=i.primary_department_id
        WHERE 1=1
    """
    params = []
    if user["role"] == "department_official":
        query += " AND EXISTS (SELECT 1 FROM incident_departments x WHERE x.incident_id=i.incident_id AND x.department_id=?)"
        params.append(user["department_id"])
    elif user["role"] == "field_worker":
        query += " AND EXISTS (SELECT 1 FROM assigned_tasks t WHERE t.incident_id=i.incident_id AND t.assigned_user_id=?)"
        params.append(user["user_id"])
    query += " ORDER BY CASE al.severity WHEN 'critical' THEN 0 ELSE 1 END, al.created_at DESC"
    with closing(get_connection()) as connection:
        rows = connection.execute(query, params).fetchall()
    return {"alerts": [dict(row) for row in rows]}


@router.get("/notifications")
def list_notifications(user=Depends(FIELD)):
    query = """
        SELECT n.*, a.area_name, i.issue_category, d.name AS department_name
        FROM notifications n
        JOIN incidents i ON i.incident_id=n.incident_id
        JOIN registered_areas a ON a.area_id=i.area_id
        JOIN departments d ON d.department_id=n.department_id
        WHERE 1=1
    """
    params = []
    if user["role"] == "department_official":
        query += " AND n.department_id=?"
        params.append(user["department_id"])
    elif user["role"] == "field_worker":
        query += """
            AND EXISTS (SELECT 1 FROM assigned_tasks t
                        WHERE t.incident_id=n.incident_id AND t.assigned_user_id=?)
        """
        params.append(user["user_id"])
    query += " ORDER BY n.scheduled_for DESC"
    with closing(get_connection()) as connection:
        rows = connection.execute(query, params).fetchall()
    return {
        "notifications": [dict(row) for row in rows],
        "delivery_notice": "Internal queue only; no SMS, email, or messaging provider is configured.",
    }


@router.get("/escalations")
def list_escalations(user=Depends(FIELD)):
    query = """
        SELECT e.*, i.area_id, a.area_name, i.issue_category, i.priority, i.status
        FROM escalation_history e JOIN incidents i ON i.incident_id=e.incident_id
        JOIN registered_areas a ON a.area_id=i.area_id
        WHERE 1=1
    """
    params = []
    if user["role"] == "department_official":
        query += " AND EXISTS (SELECT 1 FROM incident_departments x WHERE x.incident_id=i.incident_id AND x.department_id=?)"
        params.append(user["department_id"])
    elif user["role"] == "field_worker":
        query += " AND EXISTS (SELECT 1 FROM assigned_tasks t WHERE t.incident_id=i.incident_id AND t.assigned_user_id=?)"
        params.append(user["user_id"])
    query += " ORDER BY e.escalated_at DESC"
    with closing(get_connection()) as connection:
        rows = connection.execute(query, params).fetchall()
    return {"escalations": [dict(row) for row in rows]}


@router.post("/prediction-feedback", status_code=201)
def submit_prediction_feedback(
    data: PredictionFeedbackCreate,
    user=Depends(STAFF),
):
    if data.outcome not in {"failure", "no_failure", "unknown"}:
        raise HTTPException(status_code=422, detail="Unsupported outcome.")
    with closing(get_connection()) as connection:
        with connection:
            if not connection.execute(
                "SELECT 1 FROM prediction_history WHERE prediction_id=?",
                (data.prediction_id,),
            ).fetchone():
                raise HTTPException(status_code=404, detail="Prediction record not found.")
            if data.incident_id:
                _can_access_incident(connection, data.incident_id, user)
            feedback_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO prediction_feedback (
                    feedback_id, prediction_id, incident_id, outcome,
                    feedback_notes, submitted_by, submitted_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    feedback_id, data.prediction_id, data.incident_id,
                    data.outcome, data.feedback_notes, user["user_id"], utc_now(),
                ),
            )
            audit(connection, user["user_id"], "prediction.feedback_submitted", "prediction_feedback", feedback_id)
    return {"feedback_id": feedback_id, "outcome": data.outcome}


@router.get("/prediction-feedback")
def list_prediction_feedback(user=Depends(STAFF)):
    query = """
        SELECT f.*, p.ward_name, u.display_name AS submitted_by_name
        FROM prediction_feedback f
        JOIN prediction_history p ON p.prediction_id=f.prediction_id
        JOIN users u ON u.user_id=f.submitted_by
    """
    params = []
    if user["role"] == "department_official":
        query += " WHERE f.incident_id IN (SELECT incident_id FROM incident_departments WHERE department_id=?)"
        params.append(user["department_id"])
    query += " ORDER BY f.submitted_at DESC"
    with closing(get_connection()) as connection:
        rows = connection.execute(query, params).fetchall()
    return {"feedback": [dict(row) for row in rows]}


@router.get("/prediction-feedback/metrics")
def prediction_feedback_metrics(user=Depends(STAFF)):
    query = """
        SELECT p.water_supply_risk, p.waste_management_risk, p.drainage_risk,
               f.outcome
        FROM prediction_feedback f
        JOIN prediction_history p ON p.prediction_id = f.prediction_id
        WHERE f.outcome IN ('failure', 'no_failure')
    """
    parameters = []
    if user["role"] == "department_official":
        query += """
            AND f.incident_id IN (
                SELECT incident_id FROM incident_departments WHERE department_id = ?
            )
        """
        parameters.append(user["department_id"])
    with closing(get_connection()) as connection:
        rows = connection.execute(query, parameters).fetchall()
    matrix = {
        "true_positive": 0,
        "false_positive": 0,
        "true_negative": 0,
        "false_negative": 0,
    }
    for row in rows:
        predicted_high = any(
            row[column] == "High"
            for column in (
                "water_supply_risk",
                "waste_management_risk",
                "drainage_risk",
            )
        )
        failure_occurred = row["outcome"] == "failure"
        if predicted_high and failure_occurred:
            matrix["true_positive"] += 1
        elif predicted_high:
            matrix["false_positive"] += 1
        elif failure_occurred:
            matrix["false_negative"] += 1
        else:
            matrix["true_negative"] += 1
    return {
        **matrix,
        "verified_outcomes": len(rows),
        "definition": (
            "Counts use administrator/official-verified outcomes only. A prediction "
            "is considered high if any service risk label is High; this is a "
            "monitoring summary, not a recalculation of model accuracy."
        ),
    }


@router.get("/weather/status")
def weather_status(area_id: str | None = None, user=Depends(AUTHENTICATED)):
    with closing(get_connection()) as connection:
        settings = _settings(connection)
        if area_id:
            area_by_id(connection, area_id, verified=False)
            row = connection.execute(
                """
                SELECT w.*, a.area_name FROM weather_observations w
                JOIN registered_areas a ON a.area_id=w.area_id
                WHERE w.area_id=? ORDER BY w.observed_at DESC LIMIT 1
                """,
                (area_id,),
            ).fetchone()
        else:
            row = connection.execute(
                """
                SELECT w.*, a.area_name FROM weather_observations w
                JOIN registered_areas a ON a.area_id=w.area_id
                ORDER BY w.observed_at DESC LIMIT 1
                """
            ).fetchone()
        latest = dict(row) if row else None
    max_age = int(settings.get("weather_max_age_hours", "6"))
    stale = True
    if latest:
        stale = (
            datetime.now(timezone.utc)
            - datetime.fromisoformat(latest["observed_at"]).astimezone(timezone.utc)
        ) > timedelta(hours=max_age)
    return {
        "provider_configured": False,
        "provider_status": "not_configured",
        "latest_observation": latest,
        "is_stale": stale,
        "maximum_age_hours": max_age,
        "warning": (
            "No external weather provider is configured. "
            "Any stored observation is shown with its source and timestamp."
            if latest is None
            else "Weather data is stale; it is not treated as current."
            if stale
            else "A manually supplied observation is available; no external provider is configured."
        ),
        "fallback": (
            "Prediction uses values explicitly supplied in the assessment form. "
            "No live weather values are invented or substituted."
        ),
    }


@router.post("/weather/observations", status_code=201)
def create_weather_observation(data: WeatherObservationCreate, user=Depends(ADMIN)):
    observed_at = data.observed_at
    if observed_at.tzinfo is None:
        raise HTTPException(status_code=422, detail="Observation timestamp must include a timezone.")
    observed_at = observed_at.astimezone(timezone.utc)
    if observed_at > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise HTTPException(status_code=422, detail="Observation time cannot be in the future.")
    observation_id = str(uuid4())
    with closing(get_connection()) as connection:
        with connection:
            area_by_id(connection, data.area_id, verified=True)
            connection.execute(
                """
                INSERT INTO weather_observations (
                    observation_id, area_id, source, observed_at, received_at,
                    rainfall_mm, temperature_c, humidity_pct, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation_id, data.area_id, data.source.strip(),
                    observed_at.isoformat(),
                    utc_now(), data.rainfall_mm, data.temperature_c,
                    data.humidity_pct, data.notes,
                ),
            )
            audit(connection, user["user_id"], "weather.observation_recorded", "weather_observation", observation_id, {"source": data.source})
    return {"observation_id": observation_id, "received_at": utc_now()}


@router.get("/system/settings")
def get_system_settings(user=Depends(ADMIN)):
    with closing(get_connection()) as connection:
        settings = _settings(connection)
    settings["notification_provider_configured"] = False
    settings["weather_provider_configured"] = False
    return settings


@router.put("/system/settings")
def update_system_settings(data: SettingsUpdate, user=Depends(ADMIN)):
    try:
        start = datetime.strptime(data.working_hours_start, "%H:%M").time()
        end = datetime.strptime(data.working_hours_end, "%H:%M").time()
    except ValueError as error:
        raise HTTPException(status_code=422, detail="Working hours must use HH:MM format.") from error
    if start >= end or len(set(data.working_days)) != len(data.working_days) or any(
        day < 0 or day > 6 for day in data.working_days
    ):
        raise HTTPException(status_code=422, detail="Working hours or days are invalid.")
    values = data.model_dump()
    values["working_days"] = ",".join(
        str(day) for day in sorted(data.working_days)
    )
    now = utc_now()
    with closing(get_connection()) as connection:
        with connection:
            for key, value in values.items():
                connection.execute(
                    """
                    INSERT INTO system_settings (setting_key, setting_value, updated_by, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(setting_key) DO UPDATE SET
                        setting_value=excluded.setting_value,
                        updated_by=excluded.updated_by,
                        updated_at=excluded.updated_at
                    """,
                    (key, str(value), user["user_id"], now),
                )
            audit(connection, user["user_id"], "settings.updated", "system_settings", details=values)
    return {"settings": values, "notification_provider_configured": False}


@router.get("/audit-logs")
def get_audit_logs(
    limit: int = Query(default=100, ge=1, le=500),
    user=Depends(ADMIN),
):
    with closing(get_connection()) as connection:
        rows = connection.execute(
            """
            SELECT a.*, u.username
            FROM audit_logs a LEFT JOIN users u ON u.user_id=a.user_id
            ORDER BY a.created_at DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return {"audit_logs": [dict(row) for row in rows]}


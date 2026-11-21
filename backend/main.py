
import asyncio
import getpass
import logging
import os
import re
import sys
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path

import joblib
import pandas as pd
import sqlite3
import uvicorn
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database import SUPPORTED_AREAS, get_connection, initialize_database
from operations import (
    FIELD,
    create_high_risk_incident,
    router as operations_router,
    run_escalations,
    run_scheduled_notifications,
)
from security import DEMO_MODE, hash_password


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("civicpredict")
# =====================================
# 1. CREATE FASTAPI APPLICATION
# =====================================

app = FastAPI(title="CivicPredict AI API")
app.include_router(operations_router)

frontend_origin = os.environ.get("CIVICPREDICT_FRONTEND_URL", "").strip().rstrip("/")
allowed_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
if frontend_origin:
    allowed_origins.append(frontend_origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =====================================
# 2. LOAD AI MODELS
# =====================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

MODEL_DIR = os.path.join(
    BASE_DIR, "..", "ai-model", "models"
)

water_model = joblib.load(
    os.path.join(MODEL_DIR, "water_risk_model.pkl")
)

waste_model = joblib.load(
    os.path.join(MODEL_DIR, "waste_risk_model.pkl")
)

drainage_model = joblib.load(
    os.path.join(MODEL_DIR, "drainage_risk_model.pkl")
)

# =====================================
# 3. LOAD GOA DATASET
# =====================================

DATASET_PATH = os.path.join(
    BASE_DIR,
    "..",
    "ai-model",
    "dataset",
    "civicpredict_goa_synthetic_demo_dataset.csv"
)

df = pd.read_csv(DATASET_PATH)

FEATURE_COLUMNS = [
    "ward_name",
    "rainfall_mm",
    "temperature_c",
    "humidity_pct",
    "water_supply_hours",
    "water_pressure",
    "missed_pickups",
    "collection_frequency_per_week",
    "complaints_count",
    "pipeline_age_years",
    "drainage_capacity_pct",
    "previous_repairs_6m"
]
SUPPORTED_AREA_NAMES = {area.casefold(): area for area in SUPPORTED_AREAS}

# =====================================
# 4. INPUT DATA MODEL
# =====================================

class CivicData(BaseModel):
    ward_name: str
    rainfall_mm: float
    temperature_c: float
    humidity_pct: float
    water_supply_hours: float
    water_pressure: float
    missed_pickups: int
    collection_frequency_per_week: int
    complaints_count: int
    pipeline_age_years: int
    drainage_capacity_pct: float
    previous_repairs_6m: int


# =====================================
# 5. HOME API
# =====================================

@app.get("/")
def home():
    return {
        "message": "CivicPredict AI Backend is running!",
        "status": "success",
        "demo_mode": DEMO_MODE,
    }


@app.get("/demo/status")
def demo_status():
    return {
        "demo_mode": DEMO_MODE,
        "authentication_required": not DEMO_MODE,
        "notice": (
            "Demonstration environment: login is disabled and operational routes "
            "use a local demo operator."
            if DEMO_MODE
            else "Authentication is enabled."
        ),
    }


# =====================================
# 6. SINGLE AREA PREDICTION API
# =====================================
# =====================================
# PREDICTION HISTORY STORAGE
# =====================================

def prediction_row_to_dict(row):
    prediction = dict(row)
    prediction["area"] = prediction["ward_name"]
    return prediction


initialize_database()

@app.post("/predict")
def predict(data: CivicData, user=Depends(FIELD)):
    submitted_area = data.ward_name.strip()
    canonical_area = SUPPORTED_AREA_NAMES.get(submitted_area.casefold())
    if canonical_area is None:
        supported_areas = ", ".join(SUPPORTED_AREAS)
        raise HTTPException(
            status_code=400,
            detail=(
                "Unsupported area. Predictions are available only for these "
                f"15 model-supported Goa areas: {supported_areas}."
            ),
        )

    with closing(get_connection()) as connection:
        area = connection.execute(
            """
            SELECT area_name, status, model_ready
            FROM registered_areas
            WHERE area_name = ? COLLATE NOCASE
            """,
            (canonical_area,),
        ).fetchone()
    if area is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "This supported area is not registered. Ask an administrator "
                "to restore its registration before predicting."
            ),
        )
    if area["status"] != "verified" or not area["model_ready"]:
        raise HTTPException(
            status_code=422,
            detail="This area is not verified and approved for model predictions.",
        )
    prediction_data = data.model_copy(update={"ward_name": canonical_area})

    input_data = pd.DataFrame([
        prediction_data.model_dump()
    ])

    water = water_model.predict(input_data)[0]
    waste = waste_model.predict(input_data)[0]
    drainage = drainage_model.predict(input_data)[0]

    prediction_datetime = datetime.now(timezone.utc).isoformat(
        timespec="microseconds"
    )
    with closing(get_connection()) as connection:
        with connection:
            cursor = connection.execute(
                """
                INSERT INTO prediction_history (
                    ward_name,
                    prediction_datetime,
                    rainfall_mm,
                    temperature_c,
                    humidity_pct,
                    water_supply_hours,
                    water_pressure,
                    missed_pickups,
                    collection_frequency_per_week,
                    complaints_count,
                    pipeline_age_years,
                    drainage_capacity_pct,
                    previous_repairs_6m,
                    water_supply_risk,
                    waste_management_risk,
                    drainage_risk,
                    requested_by
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    canonical_area,
                    prediction_datetime,
                    data.rainfall_mm,
                    data.temperature_c,
                    data.humidity_pct,
                    data.water_supply_hours,
                    data.water_pressure,
                    data.missed_pickups,
                    data.collection_frequency_per_week,
                    data.complaints_count,
                    data.pipeline_age_years,
                    data.drainage_capacity_pct,
                    data.previous_repairs_6m,
                    str(water),
                    str(waste),
                    str(drainage),
                    user["user_id"],
                ),
            )
            prediction_id = cursor.lastrowid

    incident_id = None
    try:
        incident_id = create_high_risk_incident(
            prediction_id,
            canonical_area,
            {
                "water": str(water),
                "waste": str(waste),
                "drainage": str(drainage),
            },
        )
    except sqlite3.Error:
        logger.exception(
            "Unable to create the AI early-warning incident for prediction %s",
            prediction_id,
        )

    return {
        "prediction_id": prediction_id,
        "area": canonical_area,
        "prediction_datetime": prediction_datetime,
        "water_supply_risk": str(water),
        "waste_management_risk": str(waste),
        "drainage_risk": str(drainage),
        "incident_id": incident_id,
        "alert_warning": (
            "Prediction was saved, but its high-risk alert could not be created. "
            "Please notify the responsible department."
            if any(value == "High" for value in (str(water), str(waste), str(drainage)))
            and incident_id is None
            else None
        ),
        "source": "Synthetic demo model - not a verified real-world forecast"
    }

   
# =====================================
# PREDICTION HISTORY API
# =====================================

@app.get("/prediction-history")
def get_prediction_history(user=Depends(FIELD)):
    with closing(get_connection()) as connection:
        owner_filter = ""
        parameters = ()
        if user["role"] == "field_worker":
            owner_filter = " WHERE requested_by = ?"
            parameters = (user["user_id"],)
        total_records = connection.execute(
            f"SELECT COUNT(*) FROM prediction_history{owner_filter}",
            parameters,
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT *
            FROM prediction_history
            {owner_filter}
            ORDER BY prediction_datetime DESC, prediction_id DESC
            """,
            parameters,
        ).fetchall()

    return {
        "total_records": total_records,
        "history": [prediction_row_to_dict(row) for row in rows],
        "source": "Synthetic demo predictions"
    }


@app.get("/prediction-history/{prediction_id}")
def get_prediction_history_item(prediction_id: int, user=Depends(FIELD)):
    with closing(get_connection()) as connection:
        owner_filter = " AND requested_by = ?" if user["role"] == "field_worker" else ""
        parameters = (
            (prediction_id, user["user_id"])
            if user["role"] == "field_worker"
            else (prediction_id,)
        )
        row = connection.execute(
            f"""
            SELECT *
            FROM prediction_history
            WHERE prediction_id = ?{owner_filter}
            """,
            parameters,
        ).fetchone()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Prediction history record not found."
        )

    return prediction_row_to_dict(row)


@app.delete("/prediction-history/{prediction_id}")
def delete_prediction_history_item(prediction_id: int, user=Depends(FIELD)):
    with closing(get_connection()) as connection:
        with connection:
            owner_filter = "" if user["role"] == "administrator" else " AND requested_by = ?"
            parameters = (prediction_id,) if user["role"] == "administrator" else (
                prediction_id, user["user_id"]
            )
            linked_parameters = (
                (prediction_id,)
                if user["role"] == "administrator"
                else (prediction_id, user["user_id"])
            )
            linked_owner_filter = (
                ""
                if user["role"] == "administrator"
                else " AND p.requested_by = ?"
            )
            if connection.execute(
                f"""
                SELECT 1
                FROM incidents i
                JOIN prediction_history p ON p.prediction_id = i.prediction_id
                WHERE i.prediction_id = ?{linked_owner_filter}
                """,
                linked_parameters,
            ).fetchone():
                raise HTTPException(
                    status_code=409,
                    detail="This prediction is linked to an incident and cannot be deleted.",
                )
            cursor = connection.execute(
                f"""
                DELETE FROM prediction_history
                WHERE prediction_id = ?{owner_filter}
                """,
                parameters,
            )

    if cursor.rowcount == 0:
        raise HTTPException(
            status_code=404,
            detail="Prediction history record not found."
        )

    return {
        "prediction_id": prediction_id,
        "message": "Prediction history record deleted."
    }

# =====================================
# 7. GET ALL WARD NAMES API
# =====================================

@app.get("/wards")
def get_wards(user=Depends(FIELD)):

    wards = sorted(
        df["ward_name"].dropna().unique().tolist()
    )

    return {
        "total_wards": len(wards),
        "wards": wards,
        "source": "Synthetic demo dataset"
    }


# =====================================
# 8. WARD-WISE AI PREDICTION API
# =====================================

@app.get("/ward-predictions")
def get_ward_predictions(user=Depends(FIELD)):

    data = df.copy()

    data["date"] = pd.to_datetime(
        data["date"],
        errors="coerce"
    )

    latest_rows = (
        data.dropna(subset=["date"])
        .sort_values("date")
        .groupby("ward_name")
        .tail(1)
    )

    results = []

    for _, row in latest_rows.iterrows():

        input_data = pd.DataFrame([
            {
                column: row[column]
                for column in FEATURE_COLUMNS
            }
        ])

        water = water_model.predict(input_data)[0]
        waste = waste_model.predict(input_data)[0]
        drainage = drainage_model.predict(input_data)[0]

        results.append({
            "ward_name": str(row["ward_name"]),
            "date": row["date"].strftime("%Y-%m-%d"),
            "water_risk": str(water),
            "waste_risk": str(waste),
            "drainage_risk": str(drainage)
        })

    return {
        "total_wards": len(results),
        "predictions": results,
        "source": "Synthetic demo dataset - not verified real-world data"
    }

@app.get("/anomalies")
def get_anomalies(user=Depends(FIELD)):
    anomaly_file = (
        Path(__file__).resolve().parent.parent
        / "ai-model"
        / "dataset"
        / "anomaly_detection_results.csv"
    )

    if not anomaly_file.exists():
        raise HTTPException(
            status_code=404,
            detail="Anomaly results not found. Run anomaly_detection.py first."
        )

    df = pd.read_csv(anomaly_file)

    anomalies = df[df["anomaly_status"] == "Anomaly"]

    anomaly_records = []

    for _, row in anomalies.iterrows():
        anomaly_records.append({
            "ward_name": row["ward_name"],
            "date": str(row["date"]),
            "anomaly_status": row["anomaly_status"],
            "anomaly_score": float(row["anomaly_score"])
        })

    return {
        "total_records": len(df),
        "normal_records": int(
            (df["anomaly_status"] == "Normal").sum()
        ),
        "anomaly_count": len(anomalies),
        "anomalies": anomaly_records,
        "source": "synthetic_demo"
    }
@app.get("/model-metrics")
def get_model_metrics(user=Depends(FIELD)):
    metrics_file = (
        Path(__file__).resolve().parent.parent
        / "ai-model"
        / "models"
        / "model_metrics.json"
    )

    if not metrics_file.exists():
        return {"error": "Model metrics file not found"}

    with open(metrics_file, "r") as file:
        return json.load(file)


async def _operational_scheduler():
    while True:
        try:
            await asyncio.to_thread(run_scheduled_notifications)
            await asyncio.to_thread(run_escalations)
        except (sqlite3.Error, ValueError, HTTPException):
            logger.exception("Operational notification or escalation scheduler failed.")
        await asyncio.sleep(30)


@app.on_event("startup")
async def start_operational_scheduler():
    app.state.operational_scheduler = asyncio.create_task(_operational_scheduler())


@app.on_event("shutdown")
async def stop_operational_scheduler():
    task = getattr(app.state, "operational_scheduler", None)
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def create_initial_admin():
    if len(os.environ.get("CIVICPREDICT_SECRET_KEY", "").encode("utf-8")) < 32:
        raise SystemExit(
            "Set CIVICPREDICT_SECRET_KEY to a secret of at least 32 bytes before bootstrapping."
        )
    with closing(get_connection()) as connection:
        existing_admin = connection.execute(
            "SELECT 1 FROM users WHERE role='administrator' LIMIT 1"
        ).fetchone()
    if existing_admin:
        raise SystemExit("An administrator already exists; bootstrap is one-time only.")

    username = input("Administrator username: ").strip()
    display_name = input("Administrator display name: ").strip()
    password = getpass.getpass("Administrator password (12+ characters): ")
    if not re.fullmatch(r"[a-zA-Z0-9._-]{3,80}", username):
        raise SystemExit("Username must be 3-80 characters: letters, digits, dot, underscore or hyphen.")
    if not display_name or len(display_name) > 120:
        raise SystemExit("Display name must contain between 1 and 120 characters.")
    if len(password) < 12:
        raise SystemExit("Password must contain at least 12 characters.")
    salt, password_hash, iterations = hash_password(password)
    with closing(get_connection()) as connection:
        with connection:
            connection.execute(
                """
                INSERT INTO users (
                    username, display_name, password_hash, password_salt,
                    password_iterations, role, created_at
                )
                VALUES (?, ?, ?, ?, ?, 'administrator', ?)
                """,
                (
                    username,
                    display_name,
                    password_hash,
                    salt,
                    iterations,
                    datetime.now(timezone.utc).isoformat(timespec="microseconds"),
                ),
            )
    print(f"Administrator account '{username}' created.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "create-admin":
        create_initial_admin()
    else:
        uvicorn.run(
            "main:app",
            host=os.environ.get("CIVICPREDICT_HOST", "0.0.0.0"),
            port=int(
                os.environ.get(
                    "PORT",
                    os.environ.get("CIVICPREDICT_PORT", "8000"),
                )
            ),
        )
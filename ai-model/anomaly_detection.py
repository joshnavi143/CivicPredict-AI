
import pandas as pd
from pathlib import Path
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

# Project paths
BASE_DIR = Path(__file__).resolve().parent
DATASET_PATH = BASE_DIR / "dataset" / "civicpredict_goa_synthetic_demo_dataset.csv"
OUTPUT_PATH = BASE_DIR / "dataset" / "anomaly_detection_results.csv"

# Load dataset
df = pd.read_csv(DATASET_PATH)

# Numerical features for anomaly detection
features = [
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

# Prepare data
X = df[features].copy()

# Scale numerical values
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)

# Train Isolation Forest
model = IsolationForest(
    n_estimators=200,
    contamination=0.05,
    random_state=42
)

# Detect anomalies
predictions = model.fit_predict(X_scaled)

# Add results
df["anomaly_status"] = [
    "Anomaly" if value == -1 else "Normal"
    for value in predictions
]

df["anomaly_score"] = model.decision_function(X_scaled)

# Save results
df.to_csv(OUTPUT_PATH, index=False)

# Display summary
print("\n======================================")
print("       CIVICPREDICT AI")
print("       ANOMALY DETECTION")
print("======================================")

print("\nTotal Records:", len(df))
print("Normal Records:", (df["anomaly_status"] == "Normal").sum())
print("Anomalous Records:", (df["anomaly_status"] == "Anomaly").sum())

print("\nTop Anomalous Records:")

anomalies = df[df["anomaly_status"] == "Anomaly"]

print(
    anomalies[
        ["ward_name", "date", "anomaly_status", "anomaly_score"]
    ].sort_values("anomaly_score").head(10).to_string(index=False)
)

print("\nResults saved to:", OUTPUT_PATH)
print("\nAnomaly detection completed!")

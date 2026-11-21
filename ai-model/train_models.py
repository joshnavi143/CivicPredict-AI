
import pandas as pd
import joblib
import os
import json

from sklearn.model_selection import train_test_split
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder
from sklearn.ensemble import RandomForestClassifier
from sklearn.pipeline import Pipeline

from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    classification_report,
    confusion_matrix
)

# Load dataset
df = pd.read_csv(
    "dataset/civicpredict_goa_synthetic_demo_dataset.csv"
)

# Input features
features = [
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

X = df[features]

categorical_features = ["ward_name"]

preprocessor = ColumnTransformer([
    (
        "location",
        OneHotEncoder(handle_unknown="ignore"),
        categorical_features
    )
], remainder="passthrough")

targets = {
    "water": "water_risk",
    "waste": "waste_risk",
    "drainage": "drainage_risk"
}

os.makedirs("models", exist_ok=True)

# Store model evaluation results
all_metrics = {}

for model_name, target in targets.items():

    print("\n" + "=" * 45)
    print(f"TRAINING {model_name.upper()} MODEL")
    print("=" * 45)

    y = df[target]

    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.20,
        random_state=42,
        stratify=y
    )

    model = Pipeline([
        ("preprocessing", preprocessor),
        (
            "classifier",
            RandomForestClassifier(
                n_estimators=200,
                random_state=42,
                class_weight="balanced"
            )
        )
    ])

    # Train model
    model.fit(X_train, y_train)

    # Predictions
    predictions = model.predict(X_test)

    # Calculate metrics
    accuracy = accuracy_score(y_test, predictions)

    precision = precision_score(
        y_test, predictions,
        average="weighted",
        zero_division=0
    )

    recall = recall_score(
        y_test, predictions,
        average="weighted",
        zero_division=0
    )

    f1 = f1_score(
        y_test, predictions,
        average="weighted",
        zero_division=0
    )

    report = classification_report(
        y_test,
        predictions,
        labels=["Low", "Medium", "High"],
        output_dict=True,
        zero_division=0
    )

    matrix = confusion_matrix(
        y_test,
        predictions,
        labels=["Low", "Medium", "High"]
    )

    # Display results
    print(f"\nAccuracy: {accuracy:.4f}")
    print(f"Precision: {precision:.4f}")
    print(f"Recall: {recall:.4f}")
    print(f"F1 Score: {f1:.4f}")

    print("\nClassification Report:")
    print(classification_report(
        y_test,
        predictions,
        labels=["Low", "Medium", "High"],
        zero_division=0
    ))

    print("\nConfusion Matrix:")
    print(matrix)

    # Store results
    all_metrics[model_name] = {
        "accuracy": round(float(accuracy), 4),
        "precision": round(float(precision), 4),
        "recall": round(float(recall), 4),
        "f1_score": round(float(f1), 4),
        "class_report": report,
        "confusion_matrix": matrix.tolist(),
        "classes": ["Low", "Medium", "High"]
    }

    # Save trained model
    joblib.dump(
        model,
        f"models/{model_name}_risk_model.pkl"
    )

    print(f"\n{model_name} model saved successfully!")

# Save evaluation metrics
with open("models/model_metrics.json", "w") as file:
    json.dump(all_metrics, file, indent=4)

print("\nALL THREE MODELS TRAINED SUCCESSFULLY!")
print("Evaluation metrics saved to models/model_metrics.json")

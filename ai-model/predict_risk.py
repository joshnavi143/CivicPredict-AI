
import pandas as pd
import joblib

# Load trained models
water_model = joblib.load("models/water_risk_model.pkl")
waste_model = joblib.load("models/waste_risk_model.pkl")
drainage_model = joblib.load("models/drainage_risk_model.pkl")

# Sample area input
area_data = {
    "ward_name": ["Panaji"],
    "rainfall_mm": [150.0],
    "temperature_c": [30.0],
    "humidity_pct": [85],
    "water_supply_hours": [2.0],
    "water_pressure": [20.0],
    "missed_pickups": [6],
    "collection_frequency_per_week": [2],
    "complaints_count": [25],
    "pipeline_age_years": [35],
    "drainage_capacity_pct": [30],
    "previous_repairs_6m": [7]
}

# Convert input into DataFrame
input_df = pd.DataFrame(area_data)

# Make predictions
water_result = water_model.predict(input_df)[0]
waste_result = waste_model.predict(input_df)[0]
drainage_result = drainage_model.predict(input_df)[0]

# Display results
print("\n================================")
print("       CIVICPREDICT AI")
print("   PUBLIC SERVICE RISK REPORT")
print("================================")

print("Area:", area_data["ward_name"][0])

print("\nWater Supply Risk:", water_result)
print("Waste Management Risk:", waste_result)
print("Drainage Risk:", drainage_result)

print("\n================================")
print("       PREDICTION COMPLETED")
print("================================")

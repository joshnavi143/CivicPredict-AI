
import pandas as pd
import numpy as np

# Load dataset
file_path = "dataset/civicpredict_goa_synthetic_demo_dataset.csv"
df = pd.read_csv(file_path)

# Calculate drainage risk score
drainage_score = (
    0.40 * (df["rainfall_mm"] / df["rainfall_mm"].max()) +
    0.35 * (1 - df["drainage_capacity_pct"] / 100) +
    0.15 * (df["previous_repairs_6m"] / 9) +
    0.10 * (df["complaints_count"] / 30)
)

# Revised illustrative thresholds
df["drainage_risk"] = np.where(
    drainage_score < 0.30, "Low",
    np.where(drainage_score < 0.50, "Medium", "High")
)

# Save updated dataset
df.to_csv(file_path, index=False)

print("Drainage labels updated successfully!")
print("\nUpdated Drainage Risk Distribution:")
print(df["drainage_risk"].value_counts())

print("\nDataset saved successfully!")

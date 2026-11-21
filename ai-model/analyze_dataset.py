
import pandas as pd

# Load dataset
df = pd.read_csv(
    "dataset/civicpredict_goa_synthetic_demo_dataset.csv"
)

# 1. Dataset information
print("DATASET INFORMATION")
print("-------------------")
print("Rows:", df.shape[0])
print("Columns:", df.shape[1])

# 2. Risk distribution
print("\nWATER RISK DISTRIBUTION")
print(df["water_risk"].value_counts())

print("\nWASTE RISK DISTRIBUTION")
print(df["waste_risk"].value_counts())

print("\nDRAINAGE RISK DISTRIBUTION")
print(df["drainage_risk"].value_counts())

# 3. Unique locations
print("\nGOA LOCATIONS")
print(df["ward_name"].unique())

# 4. Duplicate records
print("\nDUPLICATE RECORDS:", df.duplicated().sum())

# 5. Data types
print("\nDATA TYPES")
print(df.dtypes)

# 6. Statistical summary
print("\nSTATISTICAL SUMMARY")
print(df.describe())

print("\nDATASET ANALYSIS COMPLETED!")

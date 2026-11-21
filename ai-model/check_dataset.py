
import pandas as pd

df = pd.read_csv("dataset/civicpredict_goa_synthetic_demo_dataset.csv")

print("Dataset Shape:", df.shape)

print("\nFirst 5 Records:")
print(df.head())

print("\nColumn Names:")
print(df.columns.tolist())

print("\nMissing Values:")
print(df.isnull().sum())

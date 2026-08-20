import pandas as pd
import json

df = pd.DataFrame({'A': [1, pd.NA, 3], 'B': ['x', 'y', pd.NA]})
for col in df.columns:
    df[col] = df[col].fillna("").astype(object)
    df.loc[df[col] == pd.NA, col] = ""

print(df)
try:
    records = df.to_dict(orient="records")
    print(records)
    print(json.dumps(records))
    print("Dump Success!")
except Exception as e:
    print("DUMP ERROR:", repr(e))

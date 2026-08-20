import pandas as pd
import numpy as np

df = pd.DataFrame({'A': [1, pd.NA, 3], 'B': ['x', 'y', pd.NA]})
print("Original DF:")
print(df)

try:
    for col in df.columns:
        df[col] = df[col].fillna("").astype(object)
        df.loc[df[col] == pd.NA, col] = ""
    print("Success!")
except Exception as e:
    print("ERROR:", repr(e))

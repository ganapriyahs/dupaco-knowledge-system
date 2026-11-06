import json, sys
import math
from collections import Counter

sys.path.insert(0, "submission")
from solution import chunk_page

snap = "snapshots/05_2026-09-28_latest"
for p in json.load(open(f"{snap}/manifest.json"))["pages"]:
    if p["url"].endswith("/rates"):
        md = open(f"{snap}/{p['file']}").read()
        for c in chunk_page(p["title"], md)[:10]:
            print(c, "\n")
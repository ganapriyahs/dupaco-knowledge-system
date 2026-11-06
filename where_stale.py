import json, re

snap = "snapshots/05_2026-09-28_latest"
pages = {}
for p in json.load(open(f"{snap}/manifest.json"))["pages"]:
    pages[p["url"]] = open(f"{snap}/{p['file']}").read()

for line in open("eval/public_eval.jsonl"):
    q = json.loads(line)
    for bad in q["must_not_include"]:
        if not re.search(r"\d", bad):
            continue
        urls = sorted(u.replace("https://www.dupaco.com", "") for u, t in pages.items() if bad in t)
        print(f"{q['id']}  stale/other value {bad!r} appears on {len(urls)} page(s): {urls[:4]}")
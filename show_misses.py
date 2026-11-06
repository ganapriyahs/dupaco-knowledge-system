import json

for line in open("results/per_question.jsonl"):
    r = json.loads(line)
    if r["score"] >= 0.99:
        continue
    print(f"{r['id']}  [{r['category']}]  score={r['score']}")
    print("  missed:", r["missed"], "| trap hits:", r["trap_hits"])
    print("  answer:", r["answer"]["text"][:220].replace("\n", " "))
    print()
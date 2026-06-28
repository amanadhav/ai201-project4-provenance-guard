"""
Milestone 3 & 4 integration test.
Submits all 4 required test inputs, prints structured results, then checks /log.
Run after the Flask server is up: python test_milestones.py
"""

import json
import urllib.request
import urllib.error

BASE = "http://localhost:5000"

TESTS = [
    {
        "label": "Clearly AI-generated",
        "creator_id": "test-ai",
        "text": (
            "Artificial intelligence represents a transformative paradigm shift in modern "
            "society. It is important to note that while the benefits of AI are numerous, it "
            "is equally essential to consider the ethical implications. Furthermore, "
            "stakeholders across various sectors must collaborate to ensure responsible "
            "deployment."
        ),
    },
    {
        "label": "Clearly human-written",
        "creator_id": "test-human",
        "text": (
            "ok so i finally tried that new ramen place downtown and honestly? "
            "underwhelming. the broth was fine but they put WAY too much sodium in it and "
            "i was thirsty for like three hours after. my friend got the spicy version and "
            "said it was better. probably won't go back unless someone drags me there"
        ),
    },
    {
        "label": "Borderline: formal human writing",
        "creator_id": "test-formal",
        "text": (
            "The relationship between monetary policy and asset price inflation has been "
            "extensively studied in the literature. Central banks face a fundamental tension "
            "between their mandate for price stability and the unintended consequences of "
            "prolonged low interest rates on equity and real estate valuations."
        ),
    },
    {
        "label": "Borderline: lightly edited AI output",
        "creator_id": "test-border",
        "text": (
            "I've been thinking a lot about remote work lately. There are genuine tradeoffs — "
            "flexibility and no commute on one side, isolation and blurred work-life boundaries "
            "on the other. Studies show productivity varies widely by individual and role type."
        ),
    },
    {
        "label": "Milestone-spec sunset sample (from M3 curl example)",
        "creator_id": "test-user-1",
        "text": (
            "The sun dipped below the horizon, painting the sky in hues of amber and rose. "
            "I sat on the porch, coffee in hand, watching the neighborhood slowly go quiet."
        ),
    },
]


def post(path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        BASE + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def get(path):
    with urllib.request.urlopen(BASE + path) as resp:
        return json.loads(resp.read())


content_ids = []

print("=" * 70)
print("MILESTONE 3 & 4  —  Signal calibration test")
print("=" * 70)

for t in TESTS:
    print(f"\n--- {t['label']} ---")
    try:
        r = post("/submit", {"text": t["text"], "creator_id": t["creator_id"]})
        content_ids.append(r["content_id"])
        print(f"  content_id     : {r['content_id']}")
        print(f"  result         : {r['result']}")
        print(f"  ai_probability : {r['ai_probability']}")
        print(f"  confidence     : {r['confidence']}")
        print(f"  label_variant  : {r['label_variant']}")
        print(f"  llm_score      : {r['signals']['llm']['score']}")
        print(f"  style_score    : {r['signals']['stylometric']['score']}")
        print(f"  llm_rationale  : {r['signals']['llm']['rationale'][:120]}...")
    except urllib.error.HTTPError as e:
        print(f"  ERROR {e.code}: {e.read().decode()}")

print()
print("=" * 70)
print("GET /log — last 5 entries")
print("=" * 70)
log = get("/log?limit=5")
print(f"  total entries in DB: {log['total']}")
for entry in log["entries"]:
    print(
        f"  {entry['created_at'][:19]}  |  {entry['result']:8s}  "
        f"|  ai_prob={entry['ai_probability']:.3f}  "
        f"|  llm={entry['llm_score']:.3f}  "
        f"|  style={entry['style_score']:.3f}  "
        f"|  {entry['content_id'][:8]}..."
    )

print()
print("=" * 70)
print("content_ids for appeal testing (Milestone 5):")
for cid in content_ids:
    print(f"  {cid}")
print("=" * 70)

# Write IDs to a file so we can reference them in M5
with open("test_content_ids.json", "w") as f:
    json.dump({"content_ids": content_ids}, f, indent=2)
print("\nSaved to test_content_ids.json")

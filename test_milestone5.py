"""
Milestone 5 — Production layer integration tests.

Covers:
  1. All three transparency label variants reachable
  2. Appeals workflow end-to-end
  3. Audit log completeness (3+ entries, both signal scores, appeal field)
  4. Rate limiting (triggers 429 after threshold)

Run: python test_milestone5.py
"""

import json
import time
import urllib.request
import urllib.error

BASE = "http://localhost:5000"

SEPARATOR = "=" * 70


def post(path, body, expect_error=False):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        BASE + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if expect_error:
            return e.code, json.loads(e.read())
        raise


def get(path):
    with urllib.request.urlopen(BASE + path) as resp:
        return json.loads(resp.read())


# ---------------------------------------------------------------------------
# Test 1: All three label variants reachable
# ---------------------------------------------------------------------------

print(SEPARATOR)
print("TEST 1 — All three transparency label variants")
print(SEPARATOR)

label_inputs = [
    {
        "name": "high_ai variant",
        "text": (
            "Artificial intelligence represents a transformative paradigm shift in modern "
            "society. It is important to note that while the benefits of AI are numerous, it "
            "is equally essential to consider the ethical implications. Furthermore, "
            "stakeholders across various sectors must collaborate to ensure responsible "
            "deployment of these technologies to maximize societal benefit."
        ),
        "creator_id": "m5-label-ai",
        "expected_variant": "high_ai",
    },
    {
        "name": "high_human variant",
        "text": (
            "ok so i finally tried that new ramen place downtown and honestly? "
            "underwhelming. the broth was fine but they put WAY too much sodium in it and "
            "i was thirsty for like three hours after. my friend got the spicy version and "
            "said it was better. probably won't go back unless someone drags me there lol"
        ),
        "creator_id": "m5-label-human",
        "expected_variant": "high_human",
    },
    {
        "name": "uncertain variant",
        "text": (
            "I've been thinking a lot about remote work lately. There are genuine tradeoffs — "
            "flexibility and no commute on one side, isolation and blurred work-life boundaries "
            "on the other. Studies show productivity varies widely by individual and role type. "
            "It's hard to say whether the shift is net positive yet."
        ),
        "creator_id": "m5-label-uncertain",
        "expected_variant": "uncertain",
    },
]

label_content_ids = {}

for t in label_inputs:
    code, r = post("/submit", {"text": t["text"], "creator_id": t["creator_id"]})
    variant = r.get("label_variant", "MISSING")
    match = "✓" if variant == t["expected_variant"] else f"✗ (expected {t['expected_variant']})"
    print(f"\n  {t['name']}")
    print(f"    content_id   : {r['content_id']}")
    print(f"    result       : {r['result']}")
    print(f"    ai_prob      : {r['ai_probability']}")
    print(f"    confidence   : {r['confidence']}")
    print(f"    label_variant: {variant}  {match}")
    print(f"    label_text   : {r['label_text'][:120]}...")
    label_content_ids[t["name"]] = r["content_id"]

# ---------------------------------------------------------------------------
# Test 2: Appeals workflow
# ---------------------------------------------------------------------------

print()
print(SEPARATOR)
print("TEST 2 — Appeals workflow")
print(SEPARATOR)

# Use the AI-labeled submission from Test 1
appeal_target = label_content_ids["high_ai variant"]
print(f"\n  Submitting appeal for content_id: {appeal_target}")

code, appeal_resp = post("/appeal", {
    "content_id": appeal_target,
    "creator_id": "m5-label-ai",
    "reason": (
        "I wrote this myself from personal experience working in tech policy. "
        "I am a non-native English speaker and my writing style tends to be formal. "
        "I can provide draft notes and timestamps."
    ),
})
print(f"  HTTP status  : {code}")
print(f"  appeal_id    : {appeal_resp.get('appeal_id')}")
print(f"  status       : {appeal_resp.get('status')}")
print(f"  message      : {appeal_resp.get('message', '')[:100]}...")

# Verify status updated in /status
print(f"\n  Checking GET /status/{appeal_target}...")
status_resp = get(f"/status/{appeal_target}")
print(f"  submission status : {status_resp['status']}")
print(f"  appeal present    : {'yes' if status_resp.get('appeal') else 'no'}")
if status_resp.get("appeal"):
    print(f"  appeal reason     : {status_resp['appeal']['reason'][:80]}...")

# Test duplicate appeal is rejected
print("\n  Testing duplicate appeal (should return 409)...")
code2, err2 = post("/appeal", {
    "content_id": appeal_target,
    "creator_id": "m5-label-ai",
    "reason": "Trying to appeal again.",
}, expect_error=True)
print(f"  HTTP status: {code2}  {'✓ 409 as expected' if code2 == 409 else '✗ unexpected'}")

# Test appeal with nonexistent content_id
print("\n  Testing appeal with invalid content_id (should return 404)...")
code3, err3 = post("/appeal", {
    "content_id": "00000000-0000-0000-0000-000000000000",
    "creator_id": "nobody",
    "reason": "This does not exist.",
}, expect_error=True)
print(f"  HTTP status: {code3}  {'✓ 404 as expected' if code3 == 404 else '✗ unexpected'}")

# ---------------------------------------------------------------------------
# Test 3: Audit log completeness
# ---------------------------------------------------------------------------

print()
print(SEPARATOR)
print("TEST 3 — Audit log completeness")
print(SEPARATOR)

log = get("/log?limit=3")
print(f"\n  Total entries in DB: {log['total']}")
required_fields = [
    "content_id", "created_at", "result", "ai_probability",
    "confidence", "llm_score", "style_score", "label_variant", "status"
]
print("\n  Checking required fields on 3 most-recent entries:")
for i, entry in enumerate(log["entries"][:3], 1):
    missing = [f for f in required_fields if f not in entry or entry[f] is None]
    status = "✓ all fields present" if not missing else f"✗ missing: {missing}"
    print(f"    Entry {i}: {entry['content_id'][:8]}...  {status}")
    print(f"      result={entry['result']}, ai_prob={entry['ai_probability']}, "
          f"llm={entry['llm_score']}, style={entry['style_score']}, "
          f"appeal={'yes' if entry.get('appeal') else 'null'}")

# ---------------------------------------------------------------------------
# Test 4: Rate limiting
# ---------------------------------------------------------------------------

print()
print(SEPARATOR)
print("TEST 4 — Rate limiting (12 rapid requests → expect 429 after 10)")
print(SEPARATOR)
print()

short_text = "This is a test submission for rate limit testing purposes only and nothing more."
results = []
for i in range(1, 13):
    try:
        code, _ = post("/submit", {
            "text": short_text,
            "creator_id": "ratelimit-test",
        }, expect_error=True)
        results.append(code)
        marker = "✓" if code == 200 else "✗ 429 RATE LIMITED"
        print(f"  Request {i:2d}: HTTP {code}  {marker}")
    except Exception as e:
        results.append("ERR")
        print(f"  Request {i:2d}: ERROR {e}")

hits_200 = results.count(200)
hits_429 = results.count(429)
print(f"\n  200 OK: {hits_200}  |  429 Rate Limited: {hits_429}")
rate_limit_ok = hits_429 > 0
print(f"  Rate limiting working: {'✓ YES' if rate_limit_ok else '✗ NO'}")

# Save full results for README
with open("milestone5_results.json", "w") as f:
    json.dump({
        "label_content_ids": label_content_ids,
        "appeal_id": appeal_resp.get("appeal_id"),
        "appeal_target_content_id": appeal_target,
        "rate_limit_results": results,
        "log_total": log["total"],
    }, f, indent=2)

print()
print(SEPARATOR)
print("All M5 tests complete. Results saved to milestone5_results.json")
print(SEPARATOR)

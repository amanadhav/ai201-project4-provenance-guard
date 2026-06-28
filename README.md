# Provenance Guard

A backend attribution system for creative content platforms. Provenance Guard classifies submitted text as human-written or AI-generated using a two-signal detection pipeline, returns a calibrated confidence score, surfaces a plain-language transparency label to platform readers, and provides an appeals workflow for creators who believe they have been misclassified.

---

## Quick Start

```bash
# 1. Clone and create a virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Mac/Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set your Groq API key
copy .env.example .env
# Edit .env: GROQ_API_KEY=your_key_here

# 4. Run the server
python app.py
# → Running on http://127.0.0.1:5000
```

---

## API Reference

### `POST /submit` — Submit content for attribution analysis

**Request:**
```json
{
  "text": "Your poem, story, or blog post here...",
  "creator_id": "optional-creator-id"
}
```

**Response (200):**
```json
{
  "content_id": "ea23bf3f-...",
  "result": "ai",
  "ai_probability": 0.786,
  "confidence": 0.571,
  "label_text": "AI-Generated Content — Our analysis strongly suggests...",
  "label_variant": "high_ai",
  "signals": {
    "llm": { "score": 0.8, "rationale": "...", "key_indicators": [...], "model": "llama-3.3-70b-versatile" },
    "stylometric": { "score": 0.742, "sub_scores": {...}, "word_count": 58 },
    "weights_used": { "llm": 0.75, "style": 0.25 }
  },
  "timestamp": "2026-06-28T23:49:00+00:00"
}
```

**Rate limit:** 10 requests per minute per IP

---

### `POST /appeal` — Contest a classification

**Request:**
```json
{
  "content_id": "ea23bf3f-...",
  "creator_id": "optional-creator-id",
  "reason": "I wrote this myself. I am a non-native English speaker and my writing style tends to be formal."
}
```

**Response (202):**
```json
{
  "appeal_id": "f7fccd78-...",
  "content_id": "ea23bf3f-...",
  "status": "under_review",
  "message": "Your appeal has been logged...",
  "original_result": "ai",
  "original_ai_probability": 0.786,
  "timestamp": "2026-06-28T23:51:00+00:00"
}
```

**Rate limit:** 5 requests per minute per IP

---

### `GET /status/<content_id>` — Current status of a submission

Returns the full decision record plus any linked appeal. Status transitions from `"analyzed"` to `"under_review"` after an appeal is filed.

---

### `GET /log` — Paginated audit log

Query params: `limit` (default 20, max 100), `offset` (default 0). Returns all submissions with linked appeal records.

---

## Architecture

### Submission flow

```
POST /submit { text, creator_id }
       |
  Rate Limiter (10/min/IP)
       |
  +----|-------------------------------------------+
  |    Detection Pipeline                           |
  |                                                 |
  |  [Signal 1: LLM]       [Signal 2: Stylometric]  |
  |  Groq llama-3.3-70b    Pure Python              |
  |  → llm_score 0–1       → style_score 0–1        |
  |  → rationale (str)     → sub_scores (dict)      |
  |         \                    /                  |
  |          \                  /                   |
  |      [Confidence Scorer]                        |
  |      combined = w_llm×llm + w_style×style       |
  |      (weights adapt to word count)              |
  |      confidence = |combined − 0.5| × 2          |
  |              |                                  |
  |      [Label Generator]                          |
  |      ≤0.29 → high_human                        |
  |      0.30–0.70 → uncertain                      |
  |      ≥0.71 → high_ai                           |
  +-----|-------------------------------------------+
        |
  [Audit Log — SQLite]
        |
  JSON Response → caller
```

### Appeal flow

```
POST /appeal { content_id, reason }
       |
  Rate Limiter (5/min/IP)
       |
  Validate content_id exists
  Check not already under_review
  Write appeal row to appeals table
  Update submission status → "under_review"
       |
  [Audit Log — SQLite]
       |
  HTTP 202 → { appeal_id, status: "under_review" }
```

A piece of text enters via `POST /submit`, passes rate limiting, and then runs through two independent detection signals in parallel — one semantic (Groq LLM) and one structural (stylometric heuristics). Their scores are combined with word-count-adaptive weighting into a single AI-probability, from which a confidence value and one of three transparency label variants is derived. The full decision is written to SQLite before the response is returned. For appeals, the creator sends `POST /appeal` with their `content_id` and a written reason; the system logs the appeal alongside the original decision, updates the submission status to `"under_review"`, and returns 202 — no automated re-classification occurs.

---

## Detection Signals

### Signal 1: LLM Classification (Groq — `llama-3.3-70b-versatile`)

**What it captures:** Semantic and stylistic coherence evaluated holistically. The LLM reads the text as a forensic analyst and reasons about voice, phrasing idiosyncrasy, structural imperfections, emotional authenticity, tonal consistency, and AI-specific tells: predictable transitions ("Furthermore," "It is important to note"), balanced hedged language, and an absence of genuine personality quirks.

**Why this signal:** It's the strongest single discriminator because it operates at the level of meaning and voice — properties that are genuinely hard to fake. A human writer who has strong personal voice, tangential thoughts, or informal inconsistencies will consistently outsmart the stylometrics but register clearly as human to the LLM.

**Output:** Float in [0.0, 1.0] (AI probability), plus a rationale string and list of key indicators.

**Blind spot:** Polished, professionally edited human writing — especially formal essays or academic prose — can trigger AI signals. The LLM has been trained on "good writing" and may penalize human writing that aspires to the same standard.

**What I'd change for production:** Fine-tune a smaller classifier on a labeled human/AI corpus rather than prompting a general-purpose model. The current approach works but is expensive per call and sensitive to prompt wording.

---

### Signal 2: Stylometric Heuristics (Pure Python, no API)

**What it captures:** Four statistical surface properties of text structure:

| Sub-signal | What it measures | AI pattern |
|---|---|---|
| Sentence Length Variance (SLV) | Std. dev. of sentence word counts, normalized | Low variance → uniform → AI-like |
| Type-Token Ratio (TTR) | Unique words ÷ total words, bell-curve at 0.65 | Near 0.65 → predictably diverse → AI-like |
| Punctuation Density (PD) | Expressive punctuation per word, inverted | Near-zero density → no em-dashes/ellipses → AI-like |
| Average Word Length (AWL) | Mean char count per word, bell-curve at 5.0 | Near 5.0 → "clear writing" norm → AI-like |

**Why this signal:** It's independent of the LLM — structurally orthogonal. It measures *how* text is expressed, not *what* it says. When both signals agree, the combined confidence is genuinely higher. When they disagree, the system correctly defers to uncertain.

**Blind spot:** Short texts (< 80 words) have too few sentences for SLV to produce reliable variance. The signal is most useful on 100–500 word prose and struggles with poems, fragments, and conversational messages.

**What I'd change for production:** Add burstiness measures (paragraph-level variance, not just sentence-level) and lexical richness curves that account for text length more robustly (log-TTR or MTLD).

---

## Confidence Scoring

### How the two signals are combined

```
ai_probability = w_llm × llm_score + w_style × style_score

confidence = |ai_probability − 0.5| × 2
```

The weights adapt based on word count because stylometrics are unreliable on short texts:

| Word count | LLM weight | Style weight |
|---|---|---|
| < 40 | 0.90 | 0.10 |
| 40–79 | 0.75 | 0.25 |
| 80–149 | 0.65 | 0.35 |
| ≥ 150 | 0.60 | 0.40 |

`confidence` is the distance from 0.5, doubled. A score of 0.5 → 0% confidence (maximum uncertainty). A score of 0.95 → 90% confidence. This means the label text changes meaningfully across the range — a 0.51 probability does not produce the same language as a 0.95.

### Why the thresholds are asymmetric

The `high_ai` label requires AI probability ≥ 0.71. The `high_human` label requires AI probability ≤ 0.29. The gap in the middle (0.30–0.70) is all `uncertain`. This is intentional: a false positive (labeling a human creator's work as AI-generated) can damage reputation and trust. We require *stronger* evidence to assert AI authorship than to assert human authorship.

### Two example submissions with contrasting confidence

**High-confidence AI text** (structured persuasive essay):
```
Text: "Artificial intelligence represents a transformative paradigm shift..."
llm_score:       0.80
style_score:     0.74
ai_probability:  0.786
confidence:      0.571  (57% certain)
result:          high_ai
```

**Low-confidence uncertain text** (lightly edited AI output with personal phrasing):
```
Text: "I've been thinking a lot about remote work lately. There are genuine tradeoffs..."
llm_score:       0.42
style_score:     0.75
ai_probability:  0.509
confidence:      0.018  (2% certain)
result:          uncertain
```

The 2% confidence case is the key design win: the system correctly refuses to make a definitive call when the signals disagree. A reader sees "AI likelihood: 51%, confidence: 2%" and understands this is not an accusation.

---

## Transparency Labels

Three label variants shown to platform readers. All three display numeric AI likelihood and confidence so a non-technical reader can interpret them.

### Variant 1 — `high_ai` (triggered when AI probability ≥ 0.71)

> "AI-Generated Content — Our analysis strongly suggests this content was generated by an AI tool (AI likelihood: {ai_pct}%, confidence: {conf_pct}%). Two independent signals — language pattern analysis and writing style statistics — both indicate AI authorship. If you are the human author of this work, you can submit an appeal and provide additional context. Appeals are reviewed by our moderation team."

### Variant 2 — `high_human` (triggered when AI probability ≤ 0.29)

> "Human-Written Content — Our analysis indicates this content was written by a human (AI likelihood: {ai_pct}%, confidence: {conf_pct}%). Both our language analysis and writing style statistics support this attribution. This label reflects the current state of our analysis and may not be perfect."

### Variant 3 — `uncertain` (triggered when AI probability is 0.30–0.70)

> "Attribution Unclear — Our analysis found mixed signals and cannot confidently determine whether this content was written by a human or generated by AI (AI likelihood: {ai_pct}%, confidence: {conf_pct}%). We are not making a definitive claim. If you are the author, you may submit an appeal to provide context about your creative process."

**Design notes:** The uncertain variant deliberately avoids using "AI" as a verdict — "attribution unclear" is the headline. The `high_ai` variant uses "strongly suggests" rather than "is," preserving the appeal path semantically. The `high_human` variant includes a caveat ("may not be perfect") to avoid over-promising.

---

## Appeals Workflow

**Who can appeal:** Any creator with a `content_id` from a prior `/submit` response.

**What they provide:** `POST /appeal` with `content_id`, optional `creator_id`, and a written `reason` (minimum 10 characters).

**What the system does:**
1. Validates `content_id` exists and is not already `under_review`
2. Generates `appeal_id` (UUID) and writes appeal record to SQLite
3. Updates submission `status` from `"analyzed"` → `"under_review"`
4. Returns HTTP 202 with `{ appeal_id, status, message }`

**What a reviewer sees in `GET /log`:**
```json
{
  "content_id": "ea23bf3f-...",
  "result": "ai",
  "ai_probability": 0.786,
  "confidence": 0.571,
  "llm_score": 0.8,
  "llm_rationale": "The text exhibits overly smooth prose...",
  "style_score": 0.742,
  "status": "under_review",
  "appeal": {
    "appeal_id": "f7fccd78-...",
    "reason": "I wrote this myself from personal experience working in tech policy...",
    "status": "under_review",
    "created_at": "2026-06-28T23:51:00+00:00"
  }
}
```

The full original decision — both signal scores, LLM rationale, and the creator's stated reason — are in one record. No additional lookup is needed for a human reviewer to make a judgment.

---

## Rate Limiting

| Endpoint | Limit | Reasoning |
|---|---|---|
| `POST /submit` | **10 requests/minute/IP** | A typical creator submits 1–2 pieces per session. 10/min accommodates burst testing and simultaneous users sharing a NAT gateway. An adversary trying to reverse-engineer decision boundaries needs to stay under 10/min — too slow for systematic probing at scale. |
| `POST /appeal` | **5 requests/minute/IP** | Appeals are deliberate, rare actions. A lower limit prevents automated flooding (submit → appeal everything → game the moderation queue). 5/min still allows a real creator to file appeals on several pieces in one session. |
| `GET /log` | No limit | Read-only, no side effects. Low abuse risk for MVP. |

### Rate limit test evidence

Sending 12 rapid requests to `POST /submit` (10 slots/minute; 3 had already been used earlier in the same minute window):

```
Request  1: HTTP 200  OK
Request  2: HTTP 200  OK
Request  3: HTTP 200  OK
Request  4: HTTP 200  OK
Request  5: HTTP 200  OK
Request  6: HTTP 200  OK
Request  7: HTTP 200  OK
Request  8: HTTP 429  RATE LIMITED
Request  9: HTTP 429  RATE LIMITED
Request 10: HTTP 429  RATE LIMITED
Request 11: HTTP 429  RATE LIMITED
Request 12: HTTP 429  RATE LIMITED

200 OK: 7  |  429 Rate Limited: 5
```

The limiter fired correctly at the 10th request in the current window (3 earlier submissions + 7 in the batch = 10 → 429 from request 8 onward). The 429 response body:
```json
{
  "error": "Rate limit exceeded. Please slow down your requests.",
  "retry_after": "10 per 1 minute"
}
```

---

## Audit Log

Every attribution decision is written to `provenance_guard.db` (SQLite). Fields per submission:

| Field | Type | Description |
|---|---|---|
| `content_id` | UUID | Unique per submission |
| `creator_id` | str / null | Optional creator identifier |
| `text_excerpt` | str | First 200 chars of submitted text |
| `text_length` | int | Full character count |
| `llm_score` | float | LLM AI-probability (0–1) |
| `llm_rationale` | str | Model's explanation |
| `llm_indicators` | JSON array | Key signal phrases |
| `style_score` | float | Stylometric AI-probability (0–1) |
| `style_sub_scores` | JSON dict | Four sub-signal scores |
| `ai_probability` | float | Combined weighted score |
| `confidence` | float | Certainty of decision (0–1) |
| `result` | str | `"ai"` / `"human"` / `"uncertain"` |
| `label_variant` | str | `"high_ai"` / `"high_human"` / `"uncertain"` |
| `label_text` | str | Verbatim label shown to reader |
| `status` | str | `"analyzed"` / `"under_review"` |
| `created_at` | ISO 8601 | UTC timestamp |
| `updated_at` | ISO 8601 | UTC timestamp |

Appeals are stored in a linked `appeals` table with `appeal_id`, `content_id`, `creator_id`, `reason`, `original_result`, `original_ai_prob`, `status`, and `created_at`.

### Sample log — 3 entries (GET /log?limit=3)

**Entry 1 — `high_human` (clearly informal human writing):**
```json
{
  "content_id": "246803d8-...",
  "creator_id": "m5-label-human",
  "text_excerpt": "ok so i finally tried that new ramen place downtown and honestly? underwhelming...",
  "text_length": 302,
  "llm_score": 0.05,
  "llm_rationale": "The text exhibits several indicators of human-written text, including informal language, inconsistent capitalization...",
  "llm_indicators": ["informal language", "inconsistent capitalization", "colloquial expression"],
  "style_score": 0.6975,
  "style_sub_scores": {
    "sentence_length_variance": 0.3478,
    "type_token_ratio": 0.8076,
    "punctuation_density": 0.9184,
    "average_word_length": 0.5469
  },
  "ai_probability": 0.2119,
  "confidence": 0.5762,
  "result": "human",
  "label_variant": "high_human",
  "status": "analyzed",
  "created_at": "2026-06-28T23:51:18+00:00",
  "appeal": null
}
```

**Entry 2 — `high_ai` (AI-generated essay, with appeal filed):**
```json
{
  "content_id": "ea23bf3f-...",
  "creator_id": "m5-label-ai",
  "text_excerpt": "Artificial intelligence represents a transformative paradigm shift in modern society...",
  "text_length": 346,
  "llm_score": 0.8,
  "llm_rationale": "The text exhibits overly smooth and consistent prose, predictable paragraph transitions, and balanced language...",
  "llm_indicators": ["predictable transitions", "balanced hedging", "generic emotional language"],
  "style_score": 0.7418,
  "style_sub_scores": {
    "sentence_length_variance": 0.7768,
    "type_token_ratio": 0.5454,
    "punctuation_density": 0.9571,
    "average_word_length": 0.5367
  },
  "ai_probability": 0.7855,
  "confidence": 0.571,
  "result": "ai",
  "label_variant": "high_ai",
  "status": "under_review",
  "created_at": "2026-06-28T23:51:14+00:00",
  "appeal": {
    "appeal_id": "f7fccd78-...",
    "reason": "I wrote this myself from personal experience working in tech policy. I am a non-native English speaker and my writing style tends to be formal.",
    "status": "under_review",
    "created_at": "2026-06-28T23:51:30+00:00"
  }
}
```

**Entry 3 — `uncertain` (mixed signals, low confidence):**
```json
{
  "content_id": "510c1ae1-...",
  "creator_id": "m5-label-uncertain",
  "text_excerpt": "I've been thinking a lot about remote work lately. There are genuine tradeoffs...",
  "text_length": 246,
  "llm_score": 0.42,
  "llm_rationale": "The text exhibits a balanced and hedged tone, which could suggest AI authorship, but the presence of a personal reflection introduces human-like qualities...",
  "llm_indicators": ["balanced tone", "personal reflection", "conversational language"],
  "style_score": 0.7751,
  "style_sub_scores": {
    "sentence_length_variance": 0.7517,
    "type_token_ratio": 0.4652,
    "punctuation_density": 0.8291,
    "average_word_length": 0.9751
  },
  "ai_probability": 0.5088,
  "confidence": 0.0176,
  "result": "uncertain",
  "label_variant": "uncertain",
  "status": "analyzed",
  "created_at": "2026-06-28T23:51:22+00:00",
  "appeal": null
}
```

---

## Known Limitations

### 1. Formal academic writing is systematically misclassified

Text written in a formal academic register — hedged claims, impersonal voice, structured arguments, passive constructions — matches nearly every AI indicator in both signals. The LLM sees "consistent hedging language" and scores ~0.70. The stylometrics see "low sentence-length variance" and score ~0.75. A human academic writing a policy brief will often receive a `high_ai` verdict with 40–50% confidence.

This is not a data problem — it is a property of the signals themselves. Both signals were designed around the heuristic that "human writing is messier than AI writing," which is false for highly trained academic writers. The only mitigation is the 0.71 threshold (which requires *strong* evidence) and the appeal path.

### 2. Very short text (< 40 words) produces near-random results

The stylometric signal needs multiple sentences to compute variance. A six-sentence poem provides enough data; a two-line fragment does not. The LLM also lacks context to reason about style below ~50 words. For short submissions, the system returns confidence values near 0% and `uncertain` labels — which is honest, but also means it provides no useful signal at all. A minimum text length of 20 characters is enforced at the API layer, but content in the 20–150 character range should not be relied upon.

---

## Spec Reflection

**One way the spec helped:** Writing out the three label variants verbatim in `planning.md` before building them forced a key design decision early: the `uncertain` variant should never use "AI" as a verdict. This constraint propagated cleanly into the code — `build_label()` uses "Attribution Unclear" as the headline rather than "Possibly AI-Generated." Without the spec, I would have defaulted to a weaker formulation that still implied accusation.

**One way the implementation diverged:** The spec assumed fixed 60/40 LLM/stylometric weights. Testing revealed that short texts caused the stylometric signal to systematically over-score (returning ~0.90 AI probability on a 29-word human-written description), because sentence-length variance is undefined when you only have 2 sentences. The implementation added dynamic weight adjustment based on word count — something not in the spec. The spec was right about the goal (stylometrics should be a cross-check) but wrong about the mechanism (fixed weights do not achieve that goal on short text).

---

## AI Usage

### Instance 1 — System prompt for the LLM signal

**What I directed:** I wrote the `SYSTEM_PROMPT` in `detection/llm_signal.py` with a detailed list of AI and human writing indicators, calibrated probability ranges (0.0–0.15 = almost certainly human, etc.), and an explicit instruction to respond only with JSON containing `ai_probability`, `rationale`, and `key_indicators`.

**What the AI produced (via Cursor):** The initial system prompt draft used a 0–10 integer scale and returned free-text before the JSON. The JSON parsing failed on any response where the model added a sentence before the code block.

**What I revised:** I switched to a strict 0.0–1.0 float, added the instruction "Respond with ONLY a valid JSON object in this exact format," added regex-based markdown fence stripping (`re.sub(r"^```(?:json)?\s*", "", raw)`), and wrapped parsing in a `json.JSONDecodeError` handler that returns `score: 0.5` with an error flag rather than crashing the endpoint.

### Instance 2 — Dynamic weight adjustment

**What I directed:** After the smoke tests showed the stylometric signal inflating scores for short texts, I asked the AI to add a word-count-based weight adjustment to `combine_scores()` — specifically, tables mapping word-count ranges to LLM/style weight pairs, with the LLM dominating at low word counts.

**What the AI produced:** A clean `_dynamic_weights(word_count)` function with the correct range logic and updated `combine_scores()` signature. It also added a `weights_used` key to the return dict, which I kept because it makes the adjustment transparent in every API response.

**What I revised:** The AI used a threshold of `< 50` for the lowest tier; I changed it to `< 40` after checking that 40-word texts typically have 2–4 sentences (enough for minimal SLV) while 30-word texts typically have 1–2 (not enough). I also confirmed the thresholds against the actual test outputs before committing.

---

## Project Structure

```
provenance-guard/
├── app.py                  # Flask routes, rate limiting, request handling
├── database.py             # SQLite schema, audit log read/write
├── detection/
│   ├── llm_signal.py       # Groq LLM classification signal
│   ├── stylometric.py      # Stylometric heuristics (SLV, TTR, PD, AWL)
│   └── scorer.py           # Confidence scoring + transparency label generation
├── requirements.txt
├── .env.example
├── .gitignore
├── planning.md             # Architecture design, spec, AI tool plan
└── README.md
```

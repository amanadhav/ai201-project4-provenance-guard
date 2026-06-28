# Provenance Guard — Planning Document

---

## Milestone 2: Full Specification

### 1. Detection Signals

#### Signal 1: LLM Classification (Groq — `llama-3.3-70b-versatile`)

**What it measures:** Semantic and stylistic coherence evaluated holistically. The LLM reads the text as a forensic analyst and reasons about whether it "feels" human — personal voice, idiosyncratic phrasing, structural imperfections, emotional authenticity, tonal consistency, and the presence or absence of AI "tells" (predictable transitions, hedged language, generic emotional vocabulary).

**Output format:** A JSON object containing:
- `score` — float in [0.0, 1.0] where 0.0 = definitely human, 1.0 = definitely AI
- `rationale` — 2–3 sentence string explaining the model's reasoning
- `key_indicators` — list of 1–3 short strings naming what it noticed (e.g. `"predictable transitions"`, `"idiosyncratic phrasing"`)
- `model` — `"llama-3.3-70b-versatile"`

**Example output (AI text):**
```json
{
  "score": 0.87,
  "rationale": "The prose is smooth and formulaic with consistent hedging language...",
  "key_indicators": ["predictable transitions", "balanced hedging", "generic emotional language"],
  "model": "llama-3.3-70b-versatile"
}
```

**Blind spot:** Highly polished, professionally edited human writing can trigger AI signals. Deliberately "casual" AI prompting can produce text that scores as human. Unreliable on texts shorter than ~50 words — too little context.

---

#### Signal 2: Stylometric Heuristics (Pure Python)

**What it measures:** Four statistical surface properties of text structure, computed without any external API:

| Sub-signal | Formula | AI pattern |
|---|---|---|
| Sentence Length Variance (SLV) | std_dev(sentence word counts), normalized to [0,1], inverted | Low variance → high AI score |
| Type-Token Ratio (TTR) | unique_words / total_words, bell-curve centered at 0.65 | Near 0.65 → higher AI score |
| Punctuation Density (PD) | expressive_punct_chars / word_count, normalized, inverted | Near-zero density → high AI score |
| Average Word Length (AWL) | mean(char_count per word), bell-curve centered at 5.0 | Near 5.0 → higher AI score |

**Output format:** A dict containing:
- `score` — float in [0.0, 1.0] where 1.0 = AI-like surface structure
- `confidence` — `"high"` / `"medium"` / `"low"` based on word count
- `sub_scores` — dict of all four individual scores
- `word_count` — integer

**Example output (AI text):**
```json
{
  "score": 0.79,
  "confidence": "high",
  "sub_scores": {
    "sentence_length_variance": 0.83,
    "type_token_ratio": 0.51,
    "punctuation_density": 1.0,
    "average_word_length": 0.48
  },
  "word_count": 104
}
```

**Stylometric sub-signal weights:**
- SLV: 50% — best single discriminator; AI text is measurably more uniform
- PD: 25% — reliable for prose; AI avoids expressive punctuation
- TTR: 15% — context-dependent; weaker alone
- AWL: 10% — weakest signal; used for tiebreaking only

**Blind spot:** Simple or informal human writing (diary entries, casual prose) naturally shows low variance and will score as AI-like. Academic human writing also has uniform sentence structure. Works best on 100–500 word prose.

---

#### Combining the two signals

```
ai_probability = (0.60 × llm_score) + (0.40 × style_score)

confidence = |ai_probability − 0.5| × 2
```

The LLM carries 60% weight because it captures semantic voice — a harder-to-fake property than surface statistics. Stylometrics carry 40% because they're independent of *what* is said and serve as a structural cross-check.

`confidence` is derived from the combined score's distance from the midpoint. A score of exactly 0.50 gives confidence 0.0 (the system has no idea). A score of 0.95 gives confidence 0.90 (very certain). This means a 0.51 AI probability and a 0.95 AI probability produce visibly different label text — not just a binary flip.

---

### 2. Uncertainty Representation

#### What a score of 0.6 means to this system

A combined `ai_probability` of 0.60 means:
- The system leans toward AI authorship but only weakly
- `confidence = |0.60 − 0.5| × 2 = 0.20` → 20% confident → **Uncertain** label
- The label explicitly says "we cannot confidently determine" and does NOT call the work AI-generated
- The creator is invited to appeal; no reputational claim is made

A score of 0.95 means:
- `confidence = 0.90` → 90% confident → **High-confidence AI** label
- The label states the work "strongly suggests AI generation"
- Still offers an appeal path

#### Thresholds

| `ai_probability` range | Label variant | Reasoning |
|---|---|---|
| ≤ 0.29 | `high_human` | Strong evidence of human authorship |
| 0.30 – 0.70 | `uncertain` | Mixed or weak signals — no definitive claim |
| ≥ 0.71 | `high_ai` | Strong evidence of AI generation |

**Why 0.71/0.29, not 0.65/0.35:** The asymmetry is intentional. We require *stronger* evidence to assert AI authorship than to assert human authorship. A false positive (labeling a human creator's work as AI-generated) damages reputation. A false negative (missing AI content) is a much lower-stakes error on this platform.

#### How scores are mapped from raw signal outputs

Each signal already outputs a 0–1 float. No additional calibration layer is applied for MVP. The confidence score itself communicates the uncertainty: the label text shows both `ai_pct` (the AI probability as a percentage) and `conf_pct` (how certain the system is). A non-technical reader sees both numbers and the label variant guides interpretation.

---

### 3. Transparency Label Design

Three label variants. All three are shown to the reader on the platform. All three include the numeric scores so a reader can see how certain the system is.

#### Variant 1 — `high_ai` (triggered when `ai_probability ≥ 0.71`)

> "AI-Generated Content — Our analysis strongly suggests this content was generated by an AI tool (AI likelihood: {ai_pct}%, confidence: {conf_pct}%). Two independent signals — language pattern analysis and writing style statistics — both indicate AI authorship. If you are the human author of this work, you can submit an appeal and provide additional context. Appeals are reviewed by our moderation team."

#### Variant 2 — `high_human` (triggered when `ai_probability ≤ 0.29`)

> "Human-Written Content — Our analysis indicates this content was written by a human (AI likelihood: {ai_pct}%, confidence: {conf_pct}%). Both our language analysis and writing style statistics support this attribution. This label reflects the current state of our analysis and may not be perfect."

#### Variant 3 — `uncertain` (triggered when `ai_probability` is 0.30–0.70)

> "Attribution Unclear — Our analysis found mixed signals and cannot confidently determine whether this content was written by a human or generated by AI (AI likelihood: {ai_pct}%, confidence: {conf_pct}%). We are not making a definitive claim. If you are the author, you may submit an appeal to provide context about your creative process."

**Label design rationale:** The uncertain variant deliberately avoids using the word "AI" as a verdict. A reader who sees "Attribution Unclear" with 52% AI likelihood and 4% confidence understands this is not an accusation. The `high_ai` variant says "strongly suggests" rather than "is" — preserving the appeal path semantically. The `high_human` variant includes a caveat ("may not be perfect") to avoid over-promising.

---

### 4. Appeals Workflow

#### Who can submit an appeal

Any creator who has a `content_id` from a prior `/submit` response can file an appeal via `POST /appeal`. No authentication is required at the MVP level — the `content_id` serves as the access token. An optional `creator_id` can be provided for human reviewers to identify the claimant.

#### What information they provide

```json
{
  "content_id": "uuid-of-original-submission",
  "creator_id": "optional-identifier-for-the-creator",
  "reason": "I wrote this poem over two weeks. I can share my draft history and handwritten notes."
}
```

`reason` is required and must be at least 10 characters. The system does not validate or score the reason — it is purely for human review.

#### What the system does when an appeal is received

1. Validates `content_id` exists in the submissions table.
2. Checks that the submission is not already `under_review` (prevents duplicate appeals).
3. Generates a new `appeal_id` (UUID).
4. Writes a row to the `appeals` table: `appeal_id`, `content_id`, `creator_id`, `reason`, `original_result`, `original_ai_prob`, `status = "under_review"`, `created_at`.
5. Updates the parent submission's `status` from `"analyzed"` → `"under_review"` and stamps `updated_at`.
6. Returns HTTP 202 with `{ appeal_id, content_id, status: "under_review", message }`.

No automated re-classification is performed. The appeal is a flag for human review only.

#### What a human reviewer sees when opening the appeal queue

`GET /log` returns all submissions with their linked appeal records in one joined response. A reviewer examining an appealed submission sees:

```
content_id:        7f4dc2a1-...
creator_id:        bob
text_excerpt:      "In today's fast-paced world, creativity has never..."
text_length:       389 characters
result:            ai
ai_probability:    0.81
confidence:        0.62
label_variant:     high_ai
llm_score:         0.87
llm_rationale:     "Smooth, formulaic prose with predictable transitions..."
llm_indicators:    ["predictable transitions", "balanced hedging"]
style_score:       0.71
style_sub_scores:  { sentence_length_variance: 0.83, ... }
status:            under_review
created_at:        2026-06-28T18:03:00Z
updated_at:        2026-06-28T18:07:00Z

appeal:
  appeal_id:       c2e91f03-...
  reason:          "I wrote this blog post myself — here is my browser history..."
  creator_id:      bob
  status:          under_review
  created_at:      2026-06-28T18:07:00Z
```

The reviewer has the original `ai_probability`, both individual signal scores and rationale, the excerpt, and the creator's stated reason — all in one record. No additional lookup is needed.

---

### 5. Anticipated Edge Cases

#### Edge case 1: The polished poem with regular meter

A human poet submits a carefully crafted poem with strict iambic pentameter and consistent rhyme scheme. Both detection signals fire in the AI direction:
- The LLM sees consistent rhythm, no tangential thoughts, and clean structure → scores ~0.60
- Stylometrics sees near-uniform sentence lengths (each line is ~10 syllables) and low punctuation density → scores ~0.55
- Combined: ~0.58 — just inside the uncertain range

**System behavior:** The creator receives an `uncertain` label with 58% AI likelihood and 16% confidence. No high-confidence AI verdict is rendered. The creator can appeal and explain their metrical constraint. This is the best the system can do without additional context — regular meter is structurally indistinguishable from AI uniformity.

**Mitigation:** The 0.71 threshold prevents a false `high_ai` label. The appeal path exists specifically for this case.

---

#### Edge case 2: Very short text (under 50 words)

A creator submits a six-word poem: *"Fog. / Then nothing. / Then you."* The system has almost no signal:
- The LLM cannot reason about style from six words → returns ~0.50 with low confidence
- Stylometrics gets only 3 sentences and 6 words → SLV is unreliable, word count triggers `"low"` confidence rating
- Combined: ~0.50 — directly in the uncertain zone

**System behavior:** The creator receives an `uncertain` label with 50% AI likelihood and 0% confidence. The label's 0% confidence number makes clear this is a non-result, not an accusation. The `POST /submit` endpoint rejects texts under 20 characters with an explicit error message.

**Mitigation:** The text length guard (min 20 chars at the API layer) catches extreme cases. For short-but-valid text, the low confidence score communicates the system's ignorance honestly.

---

#### Edge case 3: AI text deliberately "humanized" with errors

A user runs AI-generated prose through a second prompt asking it to "add typos and casual phrases." The LLM signal may not detect the underlying AI structure if the surface imperfections are convincing. The stylometric signal is more robust here: even with added typos, a 400-word AI essay will still have low sentence-length variance and low punctuation density.

**System behavior:** The LLM might score ~0.45, the stylometrics ~0.68. Combined: ~0.54 — still uncertain. The system correctly refuses to call it human (it won't reach `high_human` territory) while also not falsely over-calling it AI. This is a known hard case for any AI detection system.

---

## Architecture

### Submission Flow

```
Creator
  │
  │  POST /submit { text, creator_id }
  ▼
┌─────────────────┐
│  Rate Limiter   │──── 429 Too Many Requests (if exceeded)
│  Flask-Limiter  │
│  10 req/min/IP  │
└────────┬────────┘
         │ { text }
         ▼
┌─────────────────────────────────────────────────────┐
│              Detection Pipeline                      │
│                                                     │
│  ┌──────────────────────┐  ┌──────────────────────┐ │
│  │  Signal 1: LLM       │  │  Signal 2: Stylometry │ │
│  │  Groq API            │  │  Pure Python          │ │
│  │  llama-3.3-70b       │  │  SLV + TTR + PD + AWL │ │
│  │                      │  │                       │ │
│  │  → llm_score (0–1)   │  │  → style_score (0–1)  │ │
│  │  → rationale (str)   │  │  → sub_scores (dict)  │ │
│  └──────────┬───────────┘  └──────────┬────────────┘ │
│             └────────────┬────────────┘              │
│                          ▼                           │
│            ┌─────────────────────────────┐           │
│            │   Confidence Scorer         │           │
│            │   combined = 0.6×llm        │           │
│            │           + 0.4×style       │           │
│            │   confidence = |c−0.5| × 2  │           │
│            └────────────┬────────────────┘           │
│                         ▼                            │
│            ┌─────────────────────────┐               │
│            │  Transparency Label     │               │
│            │  Generator              │               │
│            │  score ≤ 0.29 → human   │               │
│            │  0.30–0.70 → uncertain  │               │
│            │  score ≥ 0.71 → ai      │               │
│            └────────────┬────────────┘               │
└─────────────────────────┼───────────────────────────┘
                          │ { result, ai_probability, confidence, label_text, signals }
                          ▼
              ┌───────────────────────┐
              │   Audit Log (SQLite)  │
              │   submissions table   │
              └───────────┬───────────┘
                          ▼
              JSON Response → Creator
```

### Appeal Flow

```
Creator (believes misclassified)
  │
  │  POST /appeal { content_id, creator_id, reason }
  ▼
┌─────────────────┐
│  Rate Limiter   │──── 429 Too Many Requests (if exceeded)
│  5 req/min/IP   │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  Appeal Handler                     │
│  1. Validate content_id exists      │
│  2. Check not already under_review  │
│  3. Generate appeal_id (UUID)       │
│  4. Update submission status        │
│     "analyzed" → "under_review"     │
└────────┬────────────────────────────┘
         │ { appeal_id, content_id, reason, original_result, original_ai_prob }
         ▼
┌─────────────────────────┐
│  Audit Log (SQLite)     │
│  appeals table insert   │
│  submissions table      │
│  status + updated_at    │
└────────┬────────────────┘
         ▼
JSON 202 → Creator { appeal_id, status: "under_review" }
```

**Narrative:** A piece of text enters via `POST /submit`, passes rate limiting, then runs through two independent detection signals in parallel — one semantic (LLM), one structural (stylometric heuristics). Their scores are combined with a 60/40 weighting into a single AI-probability, from which a confidence value and transparency label are derived. The full decision record is written to SQLite before the response is returned.

For appeals, the creator sends `POST /appeal` with their `content_id` and a written reason. The system validates the submission exists, writes an appeal record linked to the original decision, updates the submission's status to `under_review`, and returns a 202. No automated re-classification occurs — the appeal surfaces everything a human reviewer needs to make a judgment.

---

## AI Tool Plan

### M3 — Submission Endpoint + First Signal

**Spec sections to provide to AI tool:**
- "Detection Signals → Signal 1" (output format, prompt strategy, model name)
- "Architecture → Submission Flow" diagram

**What to ask the AI tool to generate:**
1. Flask app skeleton: `app.py` with `POST /submit` route stub, error handling, and rate limiter configuration (10/min)
2. `detection/llm_signal.py`: the Groq API call, system prompt, JSON parsing logic, and a fallback for parse failures

**How to verify output before wiring to endpoint:**
- Call `detection.llm_signal.analyze(text)` directly on 3 inputs: a clearly personal diary excerpt, a generic AI-sounding essay, and a 10-word fragment
- Check that output contains `score`, `rationale`, `key_indicators`, `model` keys
- Check that the short text input returns `score` near 0.5 (can't tell), not a crash
- Check the score direction: personal diary should score < 0.4, generic essay > 0.6

---

### M4 — Second Signal + Confidence Scoring

**Spec sections to provide to AI tool:**
- "Detection Signals → Signal 2" (four sub-signals, formula, weights)
- "Uncertainty Representation" (combination formula, confidence derivation)
- "Architecture → Submission Flow" diagram (confidence scorer box)

**What to ask the AI tool to generate:**
1. `detection/stylometric.py`: all four sub-signal functions (SLV, TTR, PD, AWL), sub-signal weighting, and the `analyze()` entry point
2. `detection/scorer.py`: `combine_scores()` function and `build_label()` function with the three label variants and threshold logic

**What to check:**
- Run stylometric analysis on the same 3 test texts from M3
- Confirm scores vary meaningfully: the AI-sounding essay should score ≥ 0.15 higher than the personal diary on `style_score`
- Confirm `combine_scores(0.14, 0.30) → ai_probability ≈ 0.20` (hits `high_human` zone)
- Confirm `combine_scores(0.87, 0.75) → ai_probability ≈ 0.82` (hits `high_ai` zone)
- Confirm `combine_scores(0.52, 0.48) → ai_probability ≈ 0.50, confidence ≈ 0.0` (deeply uncertain)
- Confirm all three label variants are reachable by constructing inputs that hit each threshold

---

### M5 — Production Layer

**Spec sections to provide to AI tool:**
- "Transparency Label Design" (exact text of all three variants)
- "Appeals Workflow" (full section — who, what, what happens, what reviewer sees)
- "Architecture → Appeal Flow" diagram

**What to ask the AI tool to generate:**
1. `database.py`: SQLite init, `log_submission()`, `log_appeal()`, `get_submission()`, `get_appeal_for_submission()`, `get_log()` with pagination
2. `POST /appeal` route in `app.py`: validation, appeal logging, status update, 202 response
3. `GET /status/<content_id>` route: return submission + any linked appeal
4. `GET /log` route: paginated audit log

**How to verify:**
- Submit text → confirm `content_id` in database
- Submit appeal with that `content_id` → confirm status changes to `under_review` in `/status` response
- Submit second appeal on same `content_id` → confirm 409 conflict (already under review)
- Query `/log` → confirm at least 3 entries with all fields present
- Confirm all three label variants appear in the log by submitting texts that hit each threshold

---

## Rate Limiting Configuration

| Endpoint | Limit | Reasoning |
|---|---|---|
| `POST /submit` | 10 requests/minute/IP | Typical creator: 1–2 submissions per session. 10/min allows burst testing without enabling adversarial probing at scale. An attacker sampling the classifier to reverse-engineer decision boundaries would need to stay under 10/min — not practical for systematic analysis. |
| `POST /appeal` | 5 requests/minute/IP | Appeals are deliberate, rare actions. Lower limit prevents automated appeal-flooding (submit garbage → appeal everything → game the system). 5/min still allows a real creator to file appeals on multiple pieces in one session. |
| `GET /log` | No limit | Read-only, no side effects. Low abuse risk for MVP. |

---

## Milestone 2 Checklist

- [x] Five questions answered with specific, implementation-ready answers
- [x] Three label variants written out verbatim (with placeholders for dynamic values)
- [x] Confidence scoring produces different labels across score range (not binary flip at 0.5)
- [x] `## Architecture` section with submission and appeal flow diagrams
- [x] 2-3 sentence architecture narrative
- [x] `## AI Tool Plan` with M3, M4, M5 — spec sections, requests, and verification steps
- [x] At least 2 specific edge cases named with concrete scenarios

---

## Milestone 3 & 4 Implementation Notes

### Dynamic weight adjustment (added during calibration)

Testing with the four milestone inputs revealed that the stylometric signal is unreliable on short texts (< 80 words). Short texts have too few sentences for SLV to measure variance meaningfully — even a human's two-sentence description scores as AI-like because there's no variation to detect.

**Fix implemented in `detection/scorer.py`:** The weight given to the stylometric signal scales with word count:

| Word count | LLM weight | Style weight | Rationale |
|---|---|---|---|
| < 40 | 0.90 | 0.10 | Stylometrics nearly useless — almost entirely LLM |
| 40–79 | 0.75 | 0.25 | Stylometrics weakly informative |
| 80–149 | 0.65 | 0.35 | Stylometrics moderately informative |
| 150+ | 0.60 | 0.40 | Full weights — both signals reliable |

The `weights_used` field is returned in every `/submit` response so the dynamic adjustment is transparent.

### M3/M4 calibration test results (4 required inputs)

| Input | LLM | Style | Combined | Result | Notes |
|---|---|---|---|---|---|
| Clearly AI-generated | 0.80 | 0.72 | 0.780 | `high_ai` ✓ | Both signals agree strongly |
| Clearly human (ramen) | 0.05 | 0.70 | 0.212 | `high_human` ✓ | Dynamic weight (75/25) lets LLM dominate |
| Formal human writing | 0.70 | 0.75 | 0.712 | `high_ai` ⚠️ | Known hard case — both signals fire; appeal path available |
| Lightly edited AI | 0.42 | 0.75 | 0.453 | `uncertain` ✓ | Correctly refuses to call it human |

**Checkpoint verified:**
- [x] Flask app runs and serves `POST /submit`
- [x] Every submission returns `content_id`, `result`, `ai_probability`, `confidence`, `label_text`, `label_variant`, `signals`
- [x] Audit log captures `llm_score`, `style_score`, `ai_probability`, `confidence`, `label_variant` per entry
- [x] `GET /log` returns paginated entries with all fields
- [x] Clearly AI text scores ~0.78; clearly human text scores ~0.21 — meaningful range

---

## Milestone 1: Original Architecture Design

*Preserved for reference.*

### Architecture Narrative

A single piece of text travels through the following path from submission to the label a user sees:

1. **Creator submits text** via `POST /submit`. The request includes the raw text and an optional `creator_id`.
2. **Rate limiter** (Flask-Limiter) checks whether this IP/creator has exceeded the allowed submission rate. If exceeded, a 429 is returned immediately.
3. **Content enters the detection pipeline.** A unique `content_id` (UUID) is generated and stamped on the submission.
4. **Signal 1 — LLM Classification (Groq):** The raw text is sent to `llama-3.3-70b-versatile` via the Groq API with a carefully crafted prompt asking it to reason about whether the text reads as human-written or AI-generated. The model returns a probability estimate (0.0 = definitely human, 1.0 = definitely AI) plus a brief rationale string.
5. **Signal 2 — Stylometric Heuristics:** The raw text is analyzed in pure Python. Four measurable statistical properties are computed: sentence length variance, type-token ratio, punctuation density, and average word length.
6. **Confidence scoring:** `combined = 0.60 × llm_score + 0.40 × stylometric_score`. `confidence = |combined − 0.5| × 2`.
7. **Transparency label generation:** Based on combined score, one of three label variants is selected.
8. **Audit log write:** Full decision record written to SQLite.
9. **Response returned** to caller.

### API Surface

| Method | Endpoint | Accepts | Returns |
|--------|----------|---------|---------|
| `POST` | `/submit` | `{ "text": str, "creator_id": str (optional) }` | `{ content_id, result, ai_probability, confidence, label_text, signals, timestamp }` |
| `POST` | `/appeal` | `{ "content_id": str, "creator_id": str, "reason": str }` | `{ appeal_id, content_id, status, message, timestamp }` |
| `GET` | `/status/<content_id>` | — | `{ content_id, result, status, ai_probability, confidence, label_text, appeal (if exists) }` |
| `GET` | `/log` | `limit`, `offset` | `{ entries: [...], total, limit, offset }` |

"""Quick smoke test — run without a Groq API key to verify all pure-Python modules."""
from detection import stylometric, scorer
import database

human_text = (
    "The rain fell sideways — I hadn't expected that. Not the rain itself, which the weather app "
    "had promised with its usual cheerful confidence, but the sideways part, the way it slapped "
    "the window and made a sound like someone shuffling cards very fast. My coffee went cold again. "
    "I've been letting things go cold lately. The kettle, the bath, my enthusiasm for finishing the "
    "novel that sits on my desk looking at me with the particular silence of something that knows "
    "you've given up on it but won't say so."
)

ai_text = (
    "In today's fast-paced world, creativity has never been more important. Whether you are an "
    "artist, a writer, or a musician, the ability to express yourself authentically is a fundamental "
    "human experience. Furthermore, creative endeavors provide not only personal fulfillment but also "
    "significant social and economic value. In addition, the rise of artificial intelligence presents "
    "both challenges and opportunities for creative professionals. By embracing these new technologies "
    "thoughtfully, we can ensure that human creativity continues to thrive."
)

print("--- Human-like text ---")
h = stylometric.analyze(human_text)
print("  style score:", h["score"])
print("  sub_scores:", h["sub_scores"])

print()
print("--- AI-like text ---")
a = stylometric.analyze(ai_text)
print("  style score:", a["score"])
print("  sub_scores:", a["sub_scores"])

print()
print("--- Scorer test ---")
s = scorer.combine_scores(0.14, h["score"])
print("  combined (human text):", s)
lb = scorer.build_label(s["ai_probability"], s["confidence"])
print("  label variant:", lb["variant"])
print("  result:", lb["result"])

s2 = scorer.combine_scores(0.87, a["score"])
print("  combined (AI text):", s2)
lb2 = scorer.build_label(s2["ai_probability"], s2["confidence"])
print("  label variant:", lb2["variant"])
print("  result:", lb2["result"])

print()
print("--- DB init test ---")
database.init_db()
print("  database initialized OK")
print()
print("All smoke tests passed.")

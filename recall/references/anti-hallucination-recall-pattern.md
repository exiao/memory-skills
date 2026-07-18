# Anti-Hallucination Recall Pattern (from DeepRecall)

Source: DeepRecall v2 by Stefan27-4 (https://github.com/Stefan27-4/DeepRecall)
Reviewed: 2026-05-28

## When to use

When standard recall (L0-L5) finds candidate files but you need high
confidence that the answer is grounded in actual past content, not
confabulated from plausible-sounding patterns. Especially useful for:
- Exact decisions or commitments ("did we agree to X or Y?")
- Specific numbers, dates, or thresholds from past sessions
- Contradictory memories where you need to resolve which is accurate

## The pattern: verbatim-quote extraction

Instead of reading a file and summarizing, force yourself through two
constrained steps:

### Step 1: Extract verbatim quotes only

When reading an episode or session file, extract ONLY text that appears
character-for-character in the source. For each quote, note the filename
and approximate line number. Do not paraphrase, summarize, or infer.

Self-prompt: "Return ONLY text that appears verbatim in this document.
Copy each relevant passage EXACTLY as it appears. If nothing relevant
is found, say so."

### Step 2: Synthesize from quotes only

Compose your answer using ONLY the extracted quotes as evidence. Cite
every claim with (filename:line). If quotes are contradictory, note the
discrepancy explicitly. If quotes don't answer the question, say so.

Self-prompt: "Base your answer ONLY on the provided quotes. Do not add
information not supported by the quotes. Cite sources. If the quotes
do not answer the question, say so honestly."

## Why it works

The two-step split prevents the common failure mode where the LLM reads
a long memory file, then generates an answer that blends real content
with plausible-sounding fabrication. By forcing verbatim extraction
first, the synthesis step has only grounded material to work with.

## Cost consideration

This pattern uses more tokens (two passes over the content instead of
one). Use it selectively when confidence matters, not for routine recall.
The standard L0-L5 progressive disclosure is cheaper and sufficient for
most queries.

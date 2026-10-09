# Editorial craft: cutting from the transcript

## Reading the plan
`cut_plan.md` shows kept text, removed words with reasons, and a review list. Read it all. For each review item decide: keep / cut / ask. The script catches: fillers, stutters (repeated word/fragment), false starts, abandoned takes, retakes (keeps the fluent one), director cues ("sorry", "again", "cut"), dead air, and non-word sounds with no transcript.

## What you can't do
You can't hear. Whisper smooths disfluencies, so stutters can be invisible in the text. Mitigations: (1) verbatim prompt, (2) untranscribed-but-not-silent regions are flagged, (3) listen-proxy: loudness/silence data + frames. State when a take choice rests on text only.

## Judgement rules
- Choose the **last complete, fluent** take unless the script says otherwise; pick by energy only if the user supplied a note.
- Cut on the word boundary with pre/post padding from config; don't clip breaths into the next word.
- Keep natural pauses ≤0.35 s for rhythm; tighten gaps over ~0.5 s. Don't remove every pause - it sounds robotic.
- Jump cuts on talking head are normal in ads; cover with B-roll, punch-in (105-115 % scale alternate) or text, don't leave long static segments.
- Check **joins**: end of one kept range + start of next must read as one sentence. Read the joined text aloud (in your head) in the plan.
- Missing parts: compare to script/brief; list missing lines as "NEEDS RETAKE" in the report - never fabricate a line.
- Hook first: if the strongest line is not first, propose a reorder (flag it; autopilot may apply it if the brief says "hook-first").

## Tamil / Tanglish
Check transcript quality on 20 s before trusting it: language auto-detect may flip. Use `--lang ta` or `--lang en` explicitly; use a larger model (`medium`/`large-v3`) if available; accept SRT from another tool via `analyze.py srt2json`. If words look wrong, lower confidence and flag; rely on silence-based cutting only (`edit_engine` silence ripple) rather than word-level cuts.

## Confidence
`cut_plan.json.confidence` 0-1. Below 0.7: say so at the top of the report and list the top 3 doubts. Autopilot still delivers.

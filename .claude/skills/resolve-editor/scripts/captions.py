#!/usr/bin/env python3
"""Plan word-pop captions (1-3 words per event, one emphasis word) from a cut plan or a transcript.

  captions.py cut_plan.json   --out captions.json [--srt captions.srt] [--kit brand-kits/x.json]
  captions.py transcript.json --out captions.json [--max-words 2] [--max-chars 16]

Input is either cut_plan.json (uses `timeline_words`: t_start/t_end on the final timeline) or an analyze.py
transcript (uses `words`: start/end in the source). Output `captions.json`:
  {"events": [{"i", "start", "end", "text", "words": [...], "emph": [word indexes], "sub": null}], "stats": {...}}
`emph` marks the word to render big / in the accent colour (numbers, brand `emphasis_words`, else the longest
content word). Chunks break on punctuation, on pauses > --gap and on --max-words / --max-chars. Pure timing and
text logic: it never touches Resolve. Style (font, colour, entrance) comes from presets + the brand kit.

Why 1-3 words: the studio's references show 1-2 word pops (one line, sometimes a small romanised-Tamil sub-word
under the English key word), kept inside the platform safe zone (platforms.md).
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import load_config, load_json, save_json  # noqa: E402

STOP = set("""a an the and or but if so to of in on at for with from by as is are was were be been am it its it's this that
these those i you he she we they me my your our their his her them us do does did done have has had not no yes can could
will would should just than then there here what which who how when where why also very really more most some any all""".split())
# frequent romanised-Tamil connectors (Tanglish): never the emphasis word
STOP_TA = set("""la le ku kku oda ooda nu nnu ana aana aanaa illa illai irukku irukkum iruku pannu panna panni pannunga
da di pa ma sari seri apdi appadi ippo ippadi athu adhu ithu idhu indha intha antha andha oru ore enna eppadi yen en
nga nga'' enga unga naan nee neenga avanga atha itha pola aprm apram""".split())
PUNCT_END = re.compile(r"[.?!;:,—…]$")
HARD_END = re.compile(r"[.?!…]$")
NUM = re.compile(r"\d")


def load_words(path):
    d = load_json(path, None)
    if d is None:
        raise SystemExit(f"cannot read {path}")
    if "timeline_words" in d:
        return [{"w": x["w"], "s": x["t_start"], "e": x["t_end"]} for x in d["timeline_words"]], d.get("timeline_duration")
    if "words" in d:
        return [{"w": x["w"], "s": x["start"], "e": x["end"]} for x in d["words"]], d.get("duration")
    raise SystemExit("input has neither timeline_words nor words")


def bare(w):
    return re.sub(r"^[^\w]+|[^\w]+$", "", w.lower())


def emphasis_index(words, kit_words):
    """Index of the word to emphasise inside one chunk, or None."""
    cand = []
    for i, w in enumerate(words):
        b = bare(w)
        if not b:
            continue
        score = 0
        if b in kit_words:
            score += 10
        if NUM.search(b) or "%" in w or "₹" in w or "rs" == b:
            score += 8
        if w.isupper() and len(b) > 1:
            score += 6
        stem = re.split(r"['’]", b)[0]  # there's / didn't / i've -> there / didn / i
        if b not in STOP and b not in STOP_TA and stem not in STOP and stem not in {"didn", "don", "isn", "wasn", "won",
                                                                                   "can", "couldn", "wouldn", "ve", "ll"}:
            score += min(len(b), 12) / 4.0
        else:
            score -= 5
        cand.append((score, i))
    if not cand:
        return None
    score, i = max(cand)
    return i if score >= 1.0 else None


def plan(words, max_words=2, max_chars=16, gap=0.35, min_hold=0.28, kit=None):
    kit = kit or {}
    cap = kit.get("captions", {})
    case = cap.get("case", "normal")
    kit_words = {bare(x) for x in cap.get("emphasis_words", [])}
    chunks, cur = [], []
    for k, w in enumerate(words):
        if cur:
            pause = w["s"] - cur[-1]["e"]
            chars = sum(len(x["w"]) + 1 for x in cur) + len(w["w"])
            if (len(cur) >= max_words or pause > gap or chars > max_chars or PUNCT_END.search(cur[-1]["w"])
                    and (len(cur) >= 1 and (HARD_END.search(cur[-1]["w"]) or len(cur) >= 2))):
                chunks.append(cur)
                cur = []
        cur.append(w)
    if cur:
        chunks.append(cur)
    events = []
    for c in chunks:
        txt = [x["w"] for x in c]
        if case == "upper":
            txt = [t.upper() for t in txt]
        elif case == "lower":
            txt = [t.lower() for t in txt]
        ei = emphasis_index([x["w"] for x in c], kit_words)
        events.append({"start": round(c[0]["s"], 3), "end": round(max(c[-1]["e"], c[0]["s"] + min_hold), 3),
                       "text": " ".join(txt), "words": txt, "emph": [] if ei is None else [ei], "sub": None})
    # no overlaps; bridge tiny gaps so text does not flicker
    for a, b in zip(events, events[1:]):
        if a["end"] > b["start"]:
            a["end"] = max(a["start"] + 0.12, b["start"])
        elif b["start"] - a["end"] < 0.15:
            a["end"] = b["start"]
    # references emphasise roughly 1 phrase in 3, never two in a row: drop the weaker of adjacent emphasised events
    for a, b in zip(events, events[1:]):
        if a["emph"] and b["emph"]:
            wa = bare(a["words"][a["emph"][0]])
            wb = bare(b["words"][b["emph"][0]])
            (b if len(wb) <= len(wa) else a)["emph"] = []
    for i, e in enumerate(events, 1):
        e["i"] = i
    return events


def srt_time(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def write_srt(events, path):
    lines = []
    for e in events:
        lines += [str(e["i"]), f"{srt_time(e['start'])} --> {srt_time(e['end'])}", e["text"], ""]
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("--out", required=True)
    ap.add_argument("--srt")
    ap.add_argument("--kit", help="brand kit json (captions.case / emphasis_words / max_words_per_line)")
    ap.add_argument("--max-words", type=int)
    ap.add_argument("--max-chars", type=int, default=16)
    ap.add_argument("--gap", type=float, default=0.35)
    a = ap.parse_args()
    kit = load_json(a.kit, {}) if a.kit else {}
    mw = a.max_words or (kit.get("captions") or {}).get("max_words_per_line") or load_config().get("captions", {}).get("max_words", 2)
    words, dur = load_words(a.input)
    ev = plan(words, mw, a.max_chars, a.gap, kit=kit)
    durs = [e["end"] - e["start"] for e in ev]
    stats = {"events": len(ev), "words": len(words), "avg_words": round(len(words) / max(len(ev), 1), 2),
             "min_dur": round(min(durs), 2) if durs else 0, "emphasised": sum(1 for e in ev if e["emph"]),
             "duration": dur, "max_words": mw}
    save_json(Path(a.out), {"events": ev, "stats": stats})
    if a.srt:
        write_srt(ev, a.srt)
    print(json.dumps(stats))


if __name__ == "__main__":
    main()

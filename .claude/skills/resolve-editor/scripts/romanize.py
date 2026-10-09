#!/usr/bin/env python3
"""Romanise the Tamil-script parts of a transcript into Tanglish (Latin letters) for captions.

  romanize.py transcript.json --out transcript.roman.json [--scheme RomanColloquial] [--style config/tanglish_style.json]

Whisper writes Tamil in Tamil script and English words in Latin. This converts ONLY the Tamil runs (Aksharamukha
"RomanColloquial") and leaves Latin runs untouched, so `websiteல` becomes `websitela` and `AI tool` stays `AI tool`
(Aksharamukha mangles Latin text, e.g. website -> websithe, so Latin must never be passed through it). A small editable
house-style dictionary then maps common outputs to the spelling the studio uses on screen
(ninka -> neenga, intha -> indha, ...); add entries as you correct captions (and tell kb.py).
Each word keeps its original under `w_ta`; `w` becomes the romanised text, so captions.py works unchanged.
Tamil has no standard romanisation: spellings are a house style, not a truth. Check proper nouns by eye.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import SKILL_DIR, load_json, save_json  # noqa: E402

TAMIL_RUN = re.compile(r"[஀-௿]+")


def load_style(path=None):
    p = Path(path) if path else SKILL_DIR / "config" / "tanglish_style.json"
    return load_json(p, {}) or {}


def roman_token(tok, scheme, style):
    from aksharamukha import transliterate
    import warnings
    warnings.filterwarnings("ignore")

    def conv(m):
        r = transliterate.process("Tamil", scheme, m.group(0))
        return style.get(r.lower(), r)
    out = TAMIL_RUN.sub(conv, tok)
    return style.get(out.lower(), out)


def romanize(t, scheme="RomanColloquial", style=None):
    style = style or {}
    for w in t.get("words", []):
        if TAMIL_RUN.search(w["w"]):
            w["w_ta"] = w["w"]
            w["w"] = roman_token(w["w"], scheme, style)
    for s in t.get("segments", []):
        if TAMIL_RUN.search(s["text"]):
            s["text_ta"] = s["text"]
            s["text"] = " ".join(roman_token(x, scheme, style) for x in s["text"].split())
    t["script"] = "romanised"
    return t


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("transcript")
    ap.add_argument("--out", required=True)
    ap.add_argument("--scheme", default="RomanColloquial")
    ap.add_argument("--style")
    a = ap.parse_args()
    t = load_json(a.transcript, None)
    if not t:
        raise SystemExit("cannot read transcript")
    out = romanize(t, a.scheme, load_style(a.style))
    save_json(a.out, out)
    print(" ".join(w["w"] for w in out["words"])[:400])


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Transcript-driven cut planner.

Reads word-level transcripts (see analyze.py) and decides what to keep: removes stutters, fillers,
false starts, abandoned takes, superseded retakes, director cues ("sorry, again") and dead air, and
returns keep-ranges in source time plus a word-level timeline map for later steps (captions, B-roll, SFX).

Usage:
  cut_plan.py --transcripts a.transcript.json [b.transcript.json ...] --out DIR [--script script.txt]
              [--edl out.edl --fps 30] [--name "Cut v1"]

Outputs in DIR:  cut_plan.json   cut_plan.md (read-through + review items)   [cut.edl]

The plan is a first-pass decision, not a verdict on performance quality. Everything uncertain lands in
`review` and lowers `confidence`; the agent must read cut_plan.md end to end before building.
"""
import argparse
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import load_config, load_json, norm_token, save_json, seconds_to_tc  # noqa: E402

SENT_END = re.compile(r"[.?!।…]$")


# ----------------------------------------------------------------------------- helpers
def sim(a, b):
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def contains_phrase(norm_toks, phrase):
    p = [norm_token(x) for x in phrase.split()]
    n = len(p)
    return any(norm_toks[i:i + n] == p for i in range(len(norm_toks) - n + 1))


def build_tokens(tr, fi):
    toks = []
    for w in tr["words"]:
        n = norm_token(w["w"])
        if not n:
            continue
        toks.append({"w": w["w"], "n": n, "start": float(w["start"]), "end": float(w["end"]),
                     "p": float(w.get("p", 1.0)), "fi": fi, "virtual": False, "removed": None})
    toks.sort(key=lambda t: (t["start"], t["end"]))
    return toks


def untranscribed_blocks(toks, silence_json, duration, ucfg):
    """Non-silent audio not covered by any word: likely an ASR-dropped 'umm', breath, or laugh."""
    if not silence_json or silence_json.get("silence_ratio", 0) < ucfg["min_silence_ratio"]:
        return [], []
    sil = sorted((s["start"], s["end"]) for s in silence_json["silence"])
    active, cur = [], 0.0
    for s, e in sil:
        if s - cur > 0.05:
            active.append((cur, s))
        cur = max(cur, e)
    if duration - cur > 0.05:
        active.append((cur, duration))
    cover = sorted((t["start"] - 0.05, t["end"] + 0.05) for t in toks)
    blocks = []
    for a, b in active:
        pos = a
        for cs, ce in cover:
            if ce <= pos:
                continue
            if cs >= b:
                break
            if cs > pos:
                blocks.append((pos, cs))
            pos = max(pos, ce)
            if pos >= b:
                break
        if pos < b:
            blocks.append((pos, b))
    cut, flag = [], []
    for s, e in blocks:
        d = e - s
        if d < ucfg["min"]:
            continue
        prev_end = max([t["end"] for t in toks if t["end"] <= s + 0.06] or [None], default=None) if toks else None
        next_start = min([t["start"] for t in toks if t["start"] >= e - 0.06] or [None], default=None) if toks else None
        bounded = (prev_end is not None and next_start is not None and s - prev_end <= ucfg["bound_gap"]
                   and next_start - e <= ucfg["bound_gap"])
        if d <= ucfg["max"] and bounded:
            cut.append((s, e))
        else:
            flag.append((s, e))
    return cut, flag


def segment(real, gap, sent_gap=0.15):
    segs, cur = [], []
    for t in real:
        if cur:
            g = t["start"] - cur[-1]["end"]
            if g > gap or (SENT_END.search(cur[-1]["w"].strip()) and g > sent_gap):
                segs.append(cur)
                cur = []
        cur.append(t)
    if cur:
        segs.append(cur)
    return segs


# ----------------------------------------------------------------------------- main planning
def plan(transcripts, cfg, script_lines=None, silences=None):
    c = cfg["cut"]
    fillers_cut = {norm_token(x) for x in c["fillers_cut"]}
    fillers_flag = {x for x in c["fillers_flag"]}
    review, discard, removed_tokens = [], [], []
    files, segments, all_by_file = [], [], {}

    # -- tokens, virtual tokens, segmentation --------------------------------------------------
    for fi, tr in enumerate(transcripts):
        files.append(tr["file"])
        real = build_tokens(tr, fi)
        sj = (silences or {}).get(fi)
        virtual = []
        if sj:
            cut_b, flag_b = untranscribed_blocks(real, sj, tr["duration"], c["untranscribed"])
            if c["untranscribed"]["action"] == "cut":
                for s, e in cut_b:
                    virtual.append({"w": "<non-word sound>", "n": "", "start": s, "end": e, "p": 1.0, "fi": fi,
                                    "virtual": True, "removed": "non-word sound (probable umm/breath)"})
            else:
                flag_b = cut_b + flag_b
            for s, e in flag_b:
                review.append({"file": tr["file"], "t": round(s, 2),
                               "why": f"{e - s:.1f}s of audio activity with no transcript (laugh? music? ASR miss?)"})
        everything = sorted(real + virtual, key=lambda t: (t["start"], t["end"]))
        all_by_file[fi] = everything
        for toks in segment(real, c["segment_gap"]):
            s0, e0 = toks[0]["start"], toks[-1]["end"]
            vin = [v for v in virtual if v["start"] >= s0 - 0.01 and v["end"] <= e0 + 0.01]
            segments.append({"id": len(segments), "fi": fi, "toks": toks, "virt": vin, "start": s0, "end": e0,
                             "status": "keep", "why": None, "fluency": 1.0, "group": None})

    # -- word-level cleanup: fillers + stutters ----------------------------------------------
    for sg in segments:
        toks = sg["toks"]
        for i, t in enumerate(toks):
            if t["n"] in fillers_cut and (t["end"] - t["start"]) < 1.0:
                t["removed"] = "filler"
        live = [t for t in toks if not t["removed"]]
        i = 0
        while i < len(live):
            hit = False
            for n in (3, 2, 1):
                a, b = live[i:i + n], live[i + n:i + 2 * n]
                if len(a) == n and len(b) == n and [x["n"] for x in a] == [x["n"] for x in b]:
                    gap = b[0]["start"] - a[-1]["end"]
                    if gap < (0.3 if n == 1 else 0.5):
                        for x in a:
                            x["removed"] = "stutter"
                        i += n
                        hit = True
                        break
            if not hit:
                i += 1
        for t in toks:
            if t["removed"]:
                removed_tokens.append({"file": files[sg["fi"]], "start": round(t["start"], 3),
                                       "end": round(t["end"], 3), "w": t["w"], "reason": t["removed"]})
        for v in sg["virt"]:
            removed_tokens.append({"file": files[sg["fi"]], "start": round(v["start"], 3),
                                   "end": round(v["end"], 3), "w": v["w"], "reason": v["removed"]})
        live = [t for t in toks if not t["removed"]]
        sg["live_n"] = [t["n"] for t in live]
        nf = sum(1 for t in toks if t["removed"] == "filler")
        ns = sum(1 for t in toks if t["removed"] == "stutter")
        nflag = sum(1 for t in live if t["n"] in fillers_flag)
        mean_p = sum(t["p"] for t in toks) / len(toks)
        sg["mean_p"] = mean_p
        sg["fluency"] = (1.0 - 0.15 * nf - 0.2 * ns - 0.1 * len(sg["virt"]) - 0.03 * min(nflag, 5)
                         - (0.3 if mean_p < 0.5 else 0.0))
        if mean_p < 0.5:
            review.append({"file": files[sg["fi"]], "t": round(sg["start"], 2),
                           "why": f"low ASR confidence ({mean_p:.2f}); transcript may be wrong here"})
        for t in toks:
            if t["end"] - t["start"] > 1.5 and not t["removed"]:
                review.append({"file": files[sg["fi"]], "t": round(t["start"], 2),
                               "why": f"word '{t['w']}' lasts {t['end'] - t['start']:.1f}s (stretched / hesitation?)"})

    def drop(sg, why):
        sg["status"], sg["why"] = "discard", why

    # -- lead-in (slate / "okay, ready") ------------------------------------------------------------
    first_of_file = {}
    for sg in segments:
        first_of_file.setdefault(sg["fi"], sg)
    for sg in first_of_file.values():
        n = sg["live_n"]
        if (n and len(n) <= c["lead_in_max_words"] and sg["start"] < c["lead_in_window"]
                and all(x in {norm_token(w) for w in c["lead_in_words"]} for x in n)):
            drop(sg, "lead-in cue before the real start")

    # -- director cues ("sorry", "again", ...) ------------------------------------------------------
    cue_phrases = c["cue_phrases"]
    for i, sg in enumerate(segments):
        if sg["status"] != "keep":
            continue
        n = sg["live_n"]
        if n and len(n) <= c["cue_max_words"] and any(contains_phrase(n, p) for p in cue_phrases):
            drop(sg, "director cue / apology (not content)")
            prev = next((s for s in reversed(segments[:i]) if s["fi"] == sg["fi"] and s["status"] == "keep"), None)
            nxt = next((s for s in segments[i + 1:] if s["fi"] == sg["fi"] and s["status"] == "keep"), None)
            if prev and sg["start"] - prev["end"] <= c["cue_context_window"]:
                if nxt and sim(prev["live_n"], nxt["live_n"]) >= 0.5:
                    drop(prev, "flubbed line before a cue, then redone")
                else:
                    review.append({"file": files[sg["fi"]], "t": round(prev["start"], 2),
                                   "why": "line before a 'sorry/again' cue was kept; check if it is a flub"})

    # -- false starts (segment is a prefix of the next one) ---------------------------------------
    for i, sg in enumerate(segments):
        if sg["status"] != "keep" or len(sg["live_n"]) < 2:
            continue
        nxt = next((s for s in segments[i + 1:] if s["fi"] == sg["fi"] and s["status"] == "keep"), None)
        if not nxt or nxt["start"] - sg["end"] > c["restart_window"]:
            continue
        a, b = sg["live_n"], nxt["live_n"]
        if len(a) < len(b) and sim(a, b[:len(a)]) >= c["restart_prefix_similarity"]:
            drop(sg, "false start (speaker restarted the sentence)")

    # -- retakes: group similar segments, keep the most fluent (ties: the later one) ----------------
    cand = [s for s in segments if s["status"] == "keep" and len(s["live_n"]) >= 3]
    parent = {s["id"]: s["id"] for s in cand}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, a in enumerate(cand):
        for b in cand[i + 1:]:
            if a["fi"] == b["fi"] and b["start"] - a["end"] > c.get("retake_window", 120):
                continue
            la, lb = len(a["live_n"]), len(b["live_n"])
            if min(la, lb) / max(la, lb) < c["retake_len_ratio"]:
                continue
            if sim(a["live_n"], b["live_n"]) >= c["retake_similarity"]:
                parent[find(a["id"])] = find(b["id"])
    groups = {}
    for s in cand:
        groups.setdefault(find(s["id"]), []).append(s)
    gnum = 0
    for members in groups.values():
        if len(members) < 2:
            continue
        gnum += 1
        maxlen = max(len(m["live_n"]) for m in members)
        for m in members:
            m["score"] = m["fluency"] + 0.1 * len(m["live_n"]) / maxlen
        ranked = sorted(members, key=lambda m: (m["score"], m["fi"], m["start"]))
        best = ranked[-1]
        for m in members:
            m["group"] = gnum
            if m is not best:
                drop(m, f"superseded: retake group {gnum}, kept take at {best['start']:.1f}s "
                        f"(file {best['fi'] + 1})")
        if len(ranked) > 1 and ranked[-1]["score"] - ranked[-2]["score"] < 0.1:
            review.append({"file": files[best["fi"]], "t": round(best["start"], 2),
                           "why": f"retake group {gnum}: close call between takes; fluency only, not performance"})
        # possible order problem: kept take lies after other kept lines that followed an earlier take
        earlier = [m for m in members if m is not best and (m["fi"], m["start"]) < (best["fi"], best["start"])]
        if earlier:
            lo = min((m["fi"], m["start"]) for m in earlier)
            between = [s for s in segments if s["status"] == "keep" and s.get("group") != gnum
                       and lo < (s["fi"], s["start"]) < (best["fi"], best["start"])]
            if between and not script_lines:
                review.append({"file": files[best["fi"]], "t": round(best["start"], 2),
                               "why": f"retake group {gnum}: line re-recorded after later lines; order may need fixing "
                                      "(supply --script to auto-order)"})

    # -- script coverage / ordering -------------------------------------------------------------------
    missing, order_key = [], {}
    if script_lines:
        kept = [s for s in segments if s["status"] == "keep"]
        matched = set()
        for s in kept:
            best_i, best_r = None, 0.0
            for li, ln in enumerate(script_lines):
                r = max(sim(s["live_n"], ln), 0.0)
                if r > best_r:
                    best_i, best_r = li, r
            if best_i is not None and best_r >= 0.5:
                order_key[s["id"]] = float(best_i)
                matched.add(best_i)
                if best_r >= 0.6:
                    pass
        for li, ln in enumerate(script_lines):
            ok = any(sim(s["live_n"], ln) >= 0.6 for s in kept)
            if not ok:
                missing.append(" ".join(ln))
                review.append({"file": "(script)", "t": 0, "why": f"script line not found in footage: \"{' '.join(ln)[:90]}\""})
        last = -1.0
        for s in sorted(kept, key=lambda s: (s["fi"], s["start"])):
            if s["id"] in order_key:
                last = order_key[s["id"]]
            else:
                order_key[s["id"]] = last + 0.01

    # -- keep ranges --------------------------------------------------------------------------------------
    kept_segs = [s for s in segments if s["status"] == "keep"]
    if script_lines:
        kept_segs.sort(key=lambda s: (order_key[s["id"]], s["fi"], s["start"]))
    else:
        kept_segs.sort(key=lambda s: (s["fi"], s["start"]))
    idx_of = {}
    for fi, lst in all_by_file.items():
        for k, t in enumerate(lst):
            idx_of[id(t)] = (fi, k)
    keep, tl_words = [], []
    offset = 0.0
    for sg in kept_segs:
        fi = sg["fi"]
        dur = transcripts[fi]["duration"]
        runs, cur, prev_idx = [], [], None
        for t in sg["toks"]:
            if t["removed"]:
                if cur:
                    runs.append(cur)
                    cur = []
                continue
            if cur and t["start"] - cur[-1]["end"] > c["max_inner_gap"]:
                runs.append(cur)
                cur = []
            # a virtual (non-word) token between two live words also splits the run
            if cur:
                a, b = cur[-1], t
                if any(v["start"] >= a["end"] - 0.02 and v["end"] <= b["start"] + 0.02 for v in sg["virt"]):
                    runs.append(cur)
                    cur = []
            cur.append(t)
        if cur:
            runs.append(cur)
        everything = all_by_file[fi]
        for run in runs:
            first, last = run[0], run[-1]
            i0, i1 = idx_of[id(first)][1], idx_of[id(last)][1]
            start = first["start"] - c["pad_pre"]
            end = last["end"] + c["pad_post"]
            if i0 > 0:
                start = max(start, min(first["start"], everything[i0 - 1]["end"] + 0.005))
            if i1 < len(everything) - 1:
                end = min(end, max(last["end"], everything[i1 + 1]["start"] - 0.005))
            start, end = max(start, 0.0), min(end, dur)
            if end - start < c["min_range"]:
                continue
            text = " ".join(t["w"] for t in run)
            keep.append({"file": files[fi], "start": round(start, 3), "end": round(end, 3), "text": text,
                         "seg_id": sg["id"], "group": sg["group"], "tl_start": round(offset, 3)})
            for t in run:
                tl_words.append({"w": t["w"], "t_start": round(offset + t["start"] - start, 3),
                                 "t_end": round(offset + t["end"] - start, 3), "file": files[fi],
                                 "src_start": round(t["start"], 3), "src_end": round(t["end"], 3),
                                 "range_idx": len(keep) - 1, "p": t["p"]})
            offset += end - start
    for k, r in enumerate(keep):
        r["tl_end"] = round(r["tl_start"] + (r["end"] - r["start"]), 3)

    for sg in segments:
        if sg["status"] == "discard":
            discard.append({"file": files[sg["fi"]], "start": round(sg["start"], 3), "end": round(sg["end"], 3),
                            "text": " ".join(t["w"] for t in sg["toks"]), "reason": sg["why"]})

    raw_total = sum(tr["duration"] for tr in transcripts)
    kept_total = sum(r["end"] - r["start"] for r in keep)
    conf = 1.0 - min(0.6, 0.04 * len(review)) - (0.1 if missing else 0.0)
    if not keep:
        conf = 0.0
    return {
        "files": files, "raw_duration": round(raw_total, 2), "kept_duration": round(kept_total, 2),
        "removed_pct": round(100 * (1 - kept_total / raw_total), 1) if raw_total else 0,
        "confidence": round(max(conf, 0.0), 2), "keep": keep, "discard": discard,
        "removed_tokens": removed_tokens, "review": review, "script_missing": missing,
        "timeline_words": tl_words, "timeline_duration": round(offset, 3),
    }


# ----------------------------------------------------------------------------- outputs
def write_md(p, path, name):
    L = [f"# Cut plan — {name}", "",
         f"- Raw: **{p['raw_duration']}s** → kept **{p['kept_duration']}s** ({p['removed_pct']}% removed)",
         f"- Ranges: {len(p['keep'])}   Discarded segments: {len(p['discard'])}   "
         f"Word-level removals: {len(p['removed_tokens'])}",
         f"- Confidence: **{p['confidence']}** (review items: {len(p['review'])})", ""]
    if p["review"]:
        L += ["## Review items (decide before building)", ""]
        for r in p["review"]:
            L.append(f"- `{Path(r['file']).name}` @ {r['t']}s — {r['why']}")
        L.append("")
    if p["script_missing"]:
        L += ["## Script lines not found in footage", ""] + [f"- {m}" for m in p["script_missing"]] + [""]
    L += ["## Discarded segments", ""]
    for d in p["discard"][:80]:
        L.append(f"- `{Path(d['file']).name}` {d['start']:.1f}–{d['end']:.1f}s — {d['reason']}: “{d['text'][:90]}”")
    if len(p["discard"]) > 80:
        L.append(f"- … {len(p['discard']) - 80} more (see cut_plan.json)")
    L += ["", "## Word-level removals (fillers / stutters / non-word sounds)", ""]
    counts = {}
    for t in p["removed_tokens"]:
        counts[t["reason"]] = counts.get(t["reason"], 0) + 1
    L += [f"- {k}: {v}" for k, v in sorted(counts.items())] + ["", "## Read-through of the kept cut (timeline order)", ""]
    for r in p["keep"]:
        L.append(f"[{r['tl_start']:6.1f}s] {r['text']}")
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def write_edl(p, path, fps, name):
    lines = [f"TITLE: {name}", "FCM: NON-DROP FRAME", ""]
    rec = 0.0
    for i, r in enumerate(p["keep"], 1):
        reel = (re.sub(r"[^A-Za-z0-9]", "", Path(r["file"]).stem).upper() or "REEL")[:8].ljust(8)
        d = r["end"] - r["start"]
        lines.append(f"{i:03d}  {reel} AA/V  C        {seconds_to_tc(r['start'], fps)} {seconds_to_tc(r['end'], fps)} "
                     f"{seconds_to_tc(rec, fps, 1)} {seconds_to_tc(rec + d, fps, 1)}")
        lines.append(f"* FROM CLIP NAME: {Path(r['file']).name}")
        rec += d
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    cfg = load_config()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--transcripts", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--script")
    ap.add_argument("--edl")
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--name", default="Cut v1")
    a = ap.parse_args()

    trs, sils = [], {}
    for i, tp in enumerate(a.transcripts):
        tr = load_json(tp)
        if not tr or "words" not in tr:
            raise SystemExit(f"{tp} is not a transcript JSON (see analyze.py transcribe)")
        trs.append(tr)
        sib = Path(tp).with_name(Path(tp).name.replace(".transcript.json", ".silence.json"))
        if sib.exists() and sib != Path(tp):
            sils[i] = load_json(sib)
    script_lines = None
    if a.script:
        raw = Path(a.script).read_text(encoding="utf-8")
        parts = [s for chunk in raw.splitlines() for s in re.split(r"(?<=[.!?।])\s+", chunk) if s.strip()]
        script_lines = [[norm_token(w) for w in s.split() if norm_token(w)] for s in parts]
        script_lines = [s for s in script_lines if s]
    p = plan(trs, cfg, script_lines, sils)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    save_json(out / "cut_plan.json", p)
    write_md(p, out / "cut_plan.md", a.name)
    if a.edl:
        write_edl(p, Path(a.edl), a.fps, a.name)
    print(f"kept {p['kept_duration']}s of {p['raw_duration']}s ({p['removed_pct']}% removed), "
          f"confidence {p['confidence']}, review items {len(p['review'])} → {out}/cut_plan.md")


if __name__ == "__main__":
    main()

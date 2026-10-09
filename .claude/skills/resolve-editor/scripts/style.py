#!/usr/bin/env python3
"""Editing styles: choose, blend and apply a style per job (the style is an INPUT, like the footage).

  style.py list
  style.py show STYLE_ID
  style.py plan --job NAME --footage FILE_OR_DIR [FILE_OR_DIR ...] [--brief "text"] [--style a | a+b]
                [--ref REFERENCE_VIDEO] [--client X] [--length SECONDS] [--lang en|ta|tanglish] [--assets-top 3]
  style.py from-reference VIDEO --id NEW_ID [--name "..."]      draft a new style from a video you like

The user can give the style as: an id, `primary+accent` (accent adds its presets/assets), a reference video
(--ref: nearest style by measured rhythm + palette), free text in --brief ("fast, yellow cards, collage"), or nothing
(auto: score by brief words, language, length, footage and what the knowledge graph learned for this client).
`plan` then: applies knowledge-graph rules (avoid / parameter overrides), runs the style's asset searches against the
indexed library (writes numbered contact sheets), records the style decision in the graph, and writes
jobs/NAME/style_plan.json + style_plan.md for the agent and the user to read before building.
Styles live in <workspace>/styles/*.json; a style is data, edit freely (status: draft-from-references | confirmed).
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import find_workspace, load_json, probe_summary, save_json  # noqa: E402

BUCKETS = [(0, 15, "under-15s"), (15, 30, "15-30s"), (30, 60, "30-60s"), (60, 90, "60-90s"), (90, 9999, "over-90s")]


def ws():
    w = find_workspace()
    if not w:
        raise SystemExit("workspace.json not found")
    return w


def load_styles():
    out = {}
    for p in sorted((ws() / "styles").glob("*.json")):
        d = load_json(p, None)
        if d and "id" in d:
            out[d["id"]] = d
    return out


def toks(text):
    return set(re.findall(r"[a-z0-9\-]+", (text or "").lower()))


def footage_profile(paths, lang=None, length=None):
    files = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            files += [f for f in sorted(p.rglob("*")) if f.suffix.lower() in {".mp4", ".mov", ".mkv", ".m4v", ".mxf"}]
        elif p.exists():
            files.append(p)
    prof = {"files": [], "tags": set()}
    total = 0.0
    for f in files:
        try:
            s = probe_summary(f)
        except Exception:  # noqa: BLE001
            continue
        total += s["duration"]
        prof["files"].append({"path": str(f), "duration": s["duration"], "res": f"{s.get('width')}x{s.get('height')}",
                              "fps": s.get("fps"), "orientation": s.get("orientation")})
        if s.get("orientation"):
            prof["tags"].add(s["orientation"])
        # reuse an existing transcript for language/quality if the workspace has one
        t = ws() / "references" / "analysis" / (f.stem + ".transcript.json")
        td = load_json(t, None) if t.exists() else None
        if td and not lang:
            lang = "tanglish" if td.get("language") == "ta" else td.get("language")
    prof["total_s"] = round(total, 1)
    if lang:
        prof["tags"].add(lang)
        if lang in ("ta", "tanglish"):
            prof["tags"].update({"tamil", "tanglish"})
    target = length or total
    for lo, hi, name in BUCKETS:
        if lo <= target < hi:
            prof["tags"].add(name)
    prof["language"] = lang
    prof["target_s"] = target
    return prof


def score_styles(styles, brief, prof, client):
    text = toks(brief) | prof["tags"]
    btext = (brief or "").lower()
    boost = {}
    try:
        from kb import Graph, slug
        g = Graph()
        seeds = [f"client:{slug(client)}"] if client else []
        act = g.activate(seeds) if seeds else {}
        boost = {k.split(":", 1)[1]: v for k, v in act.items() if k.startswith("style:")}
    except Exception:  # noqa: BLE001
        pass
    res = []
    for sid, s in styles.items():
        hit = [t for t in s.get("use_when", []) if t in text or t in btext]
        sc = len(hit) + 4.0 * boost.get(sid, 0.0)
        res.append({"id": sid, "score": round(sc, 2), "matched": hit})
    return sorted(res, key=lambda r: -r["score"])


def measure_reference(video):
    """Rhythm + palette of a video the user likes (same measures used for the studio references)."""
    from analyze import scenes
    from ingest_references import bursts, motion_energy, palette
    info = probe_summary(video)
    dur = min(info["duration"], 180)
    cuts = [c for c in scenes(video, 0.3)["cuts"] if c <= dur]
    me = motion_energy(video, info, dur)
    b = bursts(*me) if me else []
    marks = [0.0] + [x["start"] for x in b] + [dur]
    return {"duration": info["duration"], "orientation": info.get("orientation"), "avg_shot_s": round(dur / (len(cuts) + 1), 2),
            "change_every_s": round(dur / max(len(marks) - 1, 1), 2), "palette": [c["hex"] for c in palette(video, 5, True, dur)]}


def hex_dist(a, b):
    ra = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    rb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return sum((x - y) ** 2 for x, y in zip(ra, rb)) ** 0.5


def nearest_by_reference(styles, m):
    res = []
    for sid, s in styles.items():
        r = s.get("rhythm", {})
        lo, hi = r.get("avg_shot_s", [1, 3])
        mid = (lo + hi) / 2
        d_rhythm = abs(m["avg_shot_s"] - mid) / max(mid, 0.5)
        pal = s.get("colour", {}).get("palette", [])
        d_pal = 0.0
        if pal and m["palette"]:
            d_pal = sum(min(hex_dist(c, p) for p in pal) for c in m["palette"][:3]) / (3 * 441.0)
        res.append({"id": sid, "distance": round(d_rhythm + 1.5 * d_pal, 3)})
    return sorted(res, key=lambda r: r["distance"])


def run_asset_searches(style, job_dir, top, extra=None):
    try:
        from index_library import index_path, search
    except Exception:  # noqa: BLE001
        return []
    out = []
    searches = list(style.get("assets", {}).get("searches", [])) + list(extra or [])
    for i, q in enumerate(searches, 1):
        kind = q.get("kind", "assets")
        if not index_path(kind).exists():
            out.append({"query": q, "error": f"{kind} index missing: run index_library.py scan"})
            continue
        sheet = str(job_dir / "assets" / f"s{i}.jpg")
        Path(sheet).parent.mkdir(parents=True, exist_ok=True)
        try:
            res = search(kind, q.get("q", ""), top=top, sheet=sheet, category=q.get("category"))
        except SystemExit as e:
            out.append({"query": q, "error": str(e)})
            continue
        out.append({"query": q, "sheet": sheet if res else None, "candidates": res})
    return out


def cmd_list(a):
    for sid, s in load_styles().items():
        print(f"{sid:28s} [{s.get('family')}] {s.get('status', ''):24s} {s['name']}")


def cmd_show(a):
    s = load_styles().get(a.id)
    if not s:
        raise SystemExit(f"no style {a.id}")
    print(json.dumps(s, indent=1, ensure_ascii=False))


def cmd_plan(a):
    styles = load_styles()
    if not styles:
        raise SystemExit("no styles/ found")
    job_dir = ws() / "jobs" / a.job
    job_dir.mkdir(parents=True, exist_ok=True)
    prof = footage_profile(a.footage or [], a.lang, a.length)
    why = []
    if a.style:
        ids = a.style.split("+")
        for i in ids:
            if i not in styles:
                raise SystemExit(f"unknown style '{i}'. Known: {', '.join(styles)}")
        primary, accents = ids[0], ids[1:]
        why.append(f"style given by user: {a.style}")
    elif a.ref:
        m = measure_reference(a.ref)
        near = nearest_by_reference(styles, m)
        primary, accents = near[0]["id"], ([near[1]["id"]] if len(near) > 1 and near[1]["distance"] - near[0]["distance"] < 0.1 else [])
        why.append(f"nearest to reference {Path(a.ref).name}: avg shot {m['avg_shot_s']}s, change every {m['change_every_s']}s, palette {m['palette'][:3]}")
    else:
        sc = score_styles(styles, a.brief, prof, a.client)
        primary = sc[0]["id"]
        margin = sc[0]["score"] - (sc[1]["score"] if len(sc) > 1 else 0)
        accents = []
        why.append(f"auto-picked by brief/footage tags: {sc[0]['matched']} (score {sc[0]['score']}, runner-up {sc[1]['id'] if len(sc) > 1 else '-'} {sc[1]['score'] if len(sc) > 1 else ''})")
        if sc[0]["score"] == 0 or margin < 1:
            why.append("LOW CONFIDENCE: ask the user to confirm the style before building")
    style = json.loads(json.dumps(styles[primary]))
    for aid in accents:
        acc = styles[aid]
        style["presets"] = list(dict.fromkeys(style["presets"] + acc["presets"][:3]))
        style.setdefault("assets", {}).setdefault("searches", []).extend(acc.get("assets", {}).get("searches", [])[:1])
    # knowledge graph: avoid rules and parameter overrides for this client/style
    avoid, overrides, memory = [], {}, ""
    try:
        from kb import Graph, active_rules
        g = Graph()
        rules = active_rules(g, a.client, primary, a.job)
        for spec, w, nid, n in rules:
            p = n["props"]
            if p.get("polarity") == "avoid":
                avoid.append(p["text"])
                style["presets"] = [x for x in style["presets"] if f"preset:{x}" not in p.get("targets", [])]
        for spec, w, nid, n in reversed(rules):
            if n["props"].get("polarity") == "do":
                overrides.update(n["props"].get("params", {}))
    except Exception as e:  # noqa: BLE001
        memory = f"(knowledge graph unavailable: {e})"
    assets = run_asset_searches(style, job_dir, a.assets_top)
    plan = {"job": a.job, "client": a.client, "style": primary, "accents": accents, "why": why, "footage": prof["files"],
            "footage_tags": sorted(prof["tags"]), "target_s": prof["target_s"], "presets": style["presets"],
            "captions": style.get("captions"), "rhythm": style.get("rhythm"), "colour": style.get("colour"),
            "fonts": style.get("fonts"), "sfx": style.get("sfx"), "music": style.get("music"),
            "dos": style.get("dos"), "donts": style.get("donts"), "memory_avoid": avoid, "memory_overrides": overrides,
            "asset_searches": assets, "status": style.get("status"), "notes": memory}
    save_json(job_dir / "style_plan.json", plan)
    md = [f"# Style plan: {a.job}", f"**Style:** {primary}" + (f" + accents {accents}" if accents else ""),
          f"**Why:** {'; '.join(why)}", f"**Footage:** {len(prof['files'])} file(s), {prof['total_s']} s, tags {sorted(prof['tags'])}",
          f"**Presets:** {', '.join(style['presets'])}", f"**Captions:** {json.dumps(style.get('captions'))}",
          f"**Rhythm:** {json.dumps(style.get('rhythm'))}", f"**Colour:** {json.dumps(style.get('colour'))}"]
    if avoid:
        md.append("**Memory says avoid:** " + "; ".join(avoid))
    if overrides:
        md.append("**Memory overrides:** " + json.dumps(overrides))
    md.append("\n## Asset candidates (LOOK at each sheet before using)")
    for s in assets:
        q = s["query"]
        if s.get("error"):
            md.append(f"- {q.get('q')}: {s['error']}")
            continue
        md.append(f"- `{q.get('q')}` [{q.get('category', 'any')}] sheet: {s['sheet']}")
        for c in s["candidates"]:
            md.append(f"  - {c['n']}. {Path(c['path']).name} ({c.get('blend')}, alpha={c.get('alpha')}, {c['duration']}s)")
    (job_dir / "style_plan.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    try:
        from kb import Graph
        g = Graph()
        for pr in style["presets"]:
            from types import SimpleNamespace as NS
            from kb import cmd_decide
            cmd_decide(g, NS(job=a.job, client=a.client, style=primary, word=None, motion=None, preset=pr,
                             asset_cat=None, note="style plan"))
    except Exception:  # noqa: BLE001
        pass
    print(json.dumps({"style": primary, "accents": accents, "why": why, "presets": style["presets"],
                      "plan": str(job_dir / "style_plan.md")}, indent=1))


def cmd_from_reference(a):
    m = measure_reference(a.video)
    sid = a.id
    d = {"id": sid, "name": a.name or sid, "family": "custom",
         "description": f"Drafted from {Path(a.video).name}: edit this description after looking at the contact sheet.",
         "use_when": [], "source_refs": [Path(a.video).stem], "presets": [], "assets": {"categories": [], "searches": []},
         "captions": {"preset": "word-pop-caption", "max_words": 2, "case": "normal", "tanglish_subword": False},
         "rhythm": {"avg_shot_s": [round(m["avg_shot_s"] * 0.8, 1), round(m["avg_shot_s"] * 1.2, 1)],
                    "change_every_s": [round(m["change_every_s"] * 0.8, 1), round(m["change_every_s"] * 1.2, 1)]},
         "colour": {"palette": m["palette"], "look": "", "lut_hint": "", "grade": ""}, "fonts": {}, "sfx": {}, "music": {},
         "dos": [], "donts": [], "status": "draft-from-references", "measured": m}
    p = ws() / "styles" / f"{sid}.json"
    save_json(p, d)
    print(f"wrote {p}\nNEXT: run ingest_references.py on the video, LOOK at its sheet, then fill presets / assets / use_when / look, then `kb.py ingest-references`.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p = sub.add_parser("show"); p.add_argument("id")
    p = sub.add_parser("plan")
    p.add_argument("--job", required=True); p.add_argument("--footage", nargs="*")
    p.add_argument("--brief", default=""); p.add_argument("--style"); p.add_argument("--ref")
    p.add_argument("--client"); p.add_argument("--length", type=float); p.add_argument("--lang")
    p.add_argument("--assets-top", type=int, default=3)
    p = sub.add_parser("from-reference"); p.add_argument("video"); p.add_argument("--id", required=True); p.add_argument("--name")
    a = ap.parse_args()
    {"list": cmd_list, "show": cmd_show, "plan": cmd_plan, "from-reference": cmd_from_reference}[a.cmd](a)


if __name__ == "__main__":
    main()

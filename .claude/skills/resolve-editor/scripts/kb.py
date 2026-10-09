#!/usr/bin/env python3
"""Editing knowledge graph: a local, weighted, self-updating memory so the user never has to repeat a correction.

Stored in <workspace>/knowledge/ (plain JSON, small, committed to git):
  graph.json       nodes + weighted edges  (styles, presets, techniques, asset categories, words, rules, clients, jobs...)
  feedback.jsonl   append-only log of every user instruction, verbatim, with the structured rule it became
  decisions.jsonl  append-only log of editing decisions (word -> motion, style -> preset ...) per job
  KNOWLEDGE.md     human-readable export (kb.py export)

Commands (all print JSON or Markdown):
  kb.py init
  kb.py ingest-references                  build nodes/edges from presets/, styles/, style-fingerprints/ (idempotent)
  kb.py feedback --text "bigger captions" --scope client|style|global|job [--client X] [--style S] [--job J]
                 [--polarity do|avoid] [--target preset:word-pop-caption ...] [--param captions.scale=1.2 ...]
  kb.py decide --job J [--client X] [--style S] [--word W --motion M] [--preset P] [--asset-cat C] [--note ".."]
  kb.py outcome --job J --accepted | --rejected [--note ".."]      reinforce / weaken what that job used
  kb.py learn-captions captions.json [--job J --style S --client X]  word -> emphasis statistics
  kb.py learn-cutplan cut_plan.json [--client X]                     which fillers/retakes keep getting removed
  kb.py context [--client X --style S --job J --words "w1 w2"] [--budget 2500]   compact context pack for the agent
  kb.py overrides [--client X --style S --job J]                     merged parameter overrides (scripts read this)
  kb.py link A B --rel R [--w 1.0]       kb.py show NODE      kb.py search TEXT      kb.py insights      kb.py stats
  kb.py export                           kb.py sync [--push]  commit (and optionally push) knowledge/ only

Design rules
* A repeated instruction does NOT create a duplicate rule: it reinforces the existing one (weight and `count` rise),
  so frequently-stated preferences dominate retrieval. Specificity beats strength: job > client > style > global.
* Weights decay with age (edges half-life 180 d, user rules 365 d, never below 25 % for rules the user stated twice+),
  so stale habits fade but explicit corrections persist.
* `context` does spreading activation (2 hops, damped) from the seeds (client, style, brief words) so only the
  neighbourhood that matters enters the context window, in priority order, truncated to --budget characters.
"""
import argparse
import datetime as dt
import difflib
import json
import math
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import find_workspace, load_json, save_json  # noqa: E402

EDGE_HALF_LIFE_D = 180.0
RULE_HALF_LIFE_D = 365.0
MAXW = 10.0
SCOPE_RANK = {"job": 4, "client": 3, "style": 2, "global": 1}
STOP = set("a an the and or but if so to of in on at for with from by as is are was were be it its this that i you he she we they "
           "me my your our do does did not no yes can will just than then there here what which who how when where why also "
           "very really more most some any all la le ku nu da di oru ithu athu".split())


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def age_days(ts):
    try:
        t = dt.datetime.fromisoformat(ts)
        return max((dt.datetime.now(dt.timezone.utc) - t).total_seconds() / 86400.0, 0.0)
    except Exception:  # noqa: BLE001
        return 0.0


def kdir():
    ws = find_workspace()
    if not ws:
        raise SystemExit("workspace.json not found")
    d = ws / "knowledge"
    d.mkdir(exist_ok=True)
    return d


class Graph:
    def __init__(self):
        self.dir = kdir()
        self.path = self.dir / "graph.json"
        d = load_json(self.path, None) or {"version": 1, "nodes": {}, "edges": {}}
        self.nodes, self.edges = d["nodes"], d["edges"]

    # ---- persistence
    def save(self):
        save_json(self.path, {"version": 1, "nodes": self.nodes, "edges": self.edges})

    def log(self, name, rec):
        with open(self.dir / name, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # ---- nodes / edges
    def node(self, nid, label=None, **props):
        typ = nid.split(":", 1)[0]
        n = self.nodes.get(nid)
        if n is None:
            n = {"type": typ, "label": label or nid.split(":", 1)[-1], "w": 1.0, "uses": 0, "created": now(),
                 "updated": now(), "props": {}}
            self.nodes[nid] = n
        if label:
            n["label"] = label
        n["props"].update({k: v for k, v in props.items() if v is not None})
        return n

    def edge(self, a, b, rel, w=1.0, reinforce=True, auto=False):
        """Create or reinforce a directed weighted edge."""
        for x in (a, b):
            if x not in self.nodes:
                self.node(x)
        k = f"{a}|{rel}|{b}"
        e = self.edges.get(k)
        if e is None:
            self.edges[k] = {"w": float(min(w, MAXW)), "n": 1, "updated": now(), "auto": auto}
        elif reinforce:
            e["w"] = round(min(MAXW, e["w"] + w * (1 - e["w"] / MAXW)), 4)
            e["n"] += 1
            e["updated"] = now()
            e["auto"] = e.get("auto", False) and auto
        return k

    def eff(self, e, half_life=EDGE_HALF_LIFE_D):
        return e["w"] * (0.5 ** (age_days(e["updated"]) / half_life))

    def neighbours(self, nid):
        out = []
        for k, e in self.edges.items():
            a, rel, b = k.split("|")
            if a == nid:
                out.append((b, rel, self.eff(e), e))
            elif b == nid:
                out.append((a, rel, self.eff(e), e))
        return out

    # ---- spreading activation
    def activate(self, seeds, hops=2, damping=0.5):
        act = defaultdict(float)
        frontier = {s: 1.0 for s in seeds if s in self.nodes}
        for s, v in frontier.items():
            act[s] += v
        adj = defaultdict(list)
        for k, e in self.edges.items():
            a, rel, b = k.split("|")
            w = self.eff(e)
            adj[a].append((b, w))
            adj[b].append((a, w))
        for _ in range(hops):
            nxt = defaultdict(float)
            for n, v in frontier.items():
                tot = sum(w for _, w in adj[n]) or 1.0
                for m, w in adj[n]:
                    nxt[m] += v * damping * (w / tot)
            for m, v in nxt.items():
                act[m] += v
            frontier = nxt
        return act


# ------------------------------------------------------------------ helpers
def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:48] or "x"


def parse_params(items):
    out = {}
    for it in items or []:
        k, _, v = it.partition("=")
        try:
            v = json.loads(v)
        except Exception:  # noqa: BLE001
            pass
        out[k.strip()] = v
    return out


def applies(rule, client=None, style=None, job=None):
    p = rule["props"]
    sc = p.get("scope", "global")
    if sc == "global":
        return True
    if sc == "style":
        return bool(style) and p.get("style") == style
    if sc == "client":
        return bool(client) and p.get("client") == client
    if sc == "job":
        return bool(job) and p.get("job") == job
    return False


def rule_eff(g, rule):
    p = rule["props"]
    base = rule["w"] * (0.5 ** (age_days(rule["updated"]) / RULE_HALF_LIFE_D))
    if p.get("count", 1) >= 2:
        base = max(base, 0.25 * rule["w"])
    return base


# ------------------------------------------------------------------ commands
def cmd_feedback(g, a):
    scope = a.scope
    if scope == "client" and not a.client:
        raise SystemExit("--scope client needs --client")
    if scope == "style" and not a.style:
        raise SystemExit("--scope style needs --style")
    if scope == "job" and not a.job:
        raise SystemExit("--scope job needs --job")
    targets = a.target or []
    params = parse_params(a.param)
    existing = None
    for nid, n in g.nodes.items():
        if n["type"] != "rule" or n["props"].get("status") == "superseded":
            continue
        p = n["props"]
        if p.get("scope") != scope or p.get("polarity") != a.polarity:
            continue
        if scope == "client" and p.get("client") != a.client or scope == "style" and p.get("style") != a.style \
                or scope == "job" and p.get("job") != a.job:
            continue
        same_t = bool(targets) and set(targets) == set(p.get("targets", []))
        sim = difflib.SequenceMatcher(None, a.text.lower(), p.get("text", "").lower()).ratio()
        if sim >= 0.72 or (same_t and (params == p.get("params", {}) or sim >= 0.4)):
            existing = nid
            break
    if existing:
        n = g.nodes[existing]
        n["props"]["count"] = n["props"].get("count", 1) + 1
        n["props"].setdefault("evidence", []).append(a.text)
        if params:
            n["props"].setdefault("params", {}).update(params)
        n["w"] = round(min(MAXW, n["w"] + 1.0 * (1 - n["w"] / MAXW)), 3)
        n["updated"] = now()
        rid, status = existing, "reinforced"
    else:
        rid = f"rule:{slug(a.text)}-{len(g.nodes)}"
        g.node(rid, a.text[:80], text=a.text, scope=scope, client=a.client, style=a.style, job=a.job,
               polarity=a.polarity, targets=targets, params=params, count=1, status="active", evidence=[a.text])
        g.nodes[rid]["w"] = 2.0
        status = "created"
        for t in targets:
            g.edge(rid, t, "applies_to" if a.polarity == "do" else "avoids", 1.0)
        if a.client:
            g.edge(rid, f"client:{slug(a.client)}", "rule_of", 1.0)
        if a.style:
            g.edge(rid, f"style:{a.style}", "rule_of", 1.0)
        # contradiction: an active opposite-polarity rule on the same scope+targets gets superseded
        for oid, o in list(g.nodes.items()):
            if o["type"] == "rule" and oid != rid and o["props"].get("status") == "active" \
                    and o["props"].get("scope") == scope and o["props"].get("polarity") != a.polarity \
                    and targets and set(targets) & set(o["props"].get("targets", [])) \
                    and o["props"].get("client") == a.client and o["props"].get("style") == a.style:
                o["props"]["status"] = "superseded"
                o["props"]["superseded_by"] = rid
    g.log("feedback.jsonl", {"t": now(), "text": a.text, "scope": scope, "client": a.client, "style": a.style,
                             "job": a.job, "polarity": a.polarity, "targets": targets, "params": params,
                             "rule": rid, "status": status})
    g.save()
    print(json.dumps({"rule": rid, "status": status, "count": g.nodes[rid]["props"]["count"],
                      "weight": g.nodes[rid]["w"]}))


def cmd_decide(g, a):
    touched = []
    cl = f"client:{slug(a.client)}" if a.client else None
    st = f"style:{a.style}" if a.style else None
    jb = f"job:{slug(a.job)}"
    g.node(jb, a.job, client=a.client, style=a.style)
    if cl:
        g.edge(jb, cl, "for_client", 0.5, reinforce=False)
    if st:
        g.edge(jb, st, "uses_style", 0.5, reinforce=False)
    if a.word and a.motion:
        w, m = f"word:{slug(a.word)}", f"motion:{slug(a.motion)}"
        g.node(w, a.word)
        g.node(m, a.motion)
        touched.append(g.edge(w, m, "gets_motion", 0.3))
        if a.preset:
            touched.append(g.edge(m, f"preset:{a.preset}", "implemented_by", 0.3))
    if a.preset:
        pid = f"preset:{a.preset}"
        if st:
            touched.append(g.edge(st, pid, "uses_preset", 0.2))
        if cl:
            touched.append(g.edge(cl, pid, "prefers", 0.2))
    if a.asset_cat:
        ac = f"asset_cat:{slug(a.asset_cat)}"
        g.node(ac, a.asset_cat)
        if st:
            touched.append(g.edge(st, ac, "draws_on", 0.2))
        if a.preset:
            touched.append(g.edge(f"preset:{a.preset}", ac, "draws_on", 0.2))
    g.log("decisions.jsonl", {"t": now(), "job": a.job, "client": a.client, "style": a.style, "word": a.word,
                              "motion": a.motion, "preset": a.preset, "asset_cat": a.asset_cat, "note": a.note,
                              "edges": touched})
    g.save()
    print(json.dumps({"decision_edges": touched}))


def cmd_outcome(g, a):
    amount = 0.4 if a.accepted else -0.5
    n = 0
    p = g.dir / "decisions.jsonl"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r["job"] != a.job:
                continue
            for k in r.get("edges", []):
                e = g.edges.get(k)
                if e:
                    e["w"] = round(max(0.05, min(MAXW, e["w"] + amount * (1 - e["w"] / MAXW if amount > 0 else 1))), 4)
                    e["updated"] = now()
                    n += 1
    g.log("decisions.jsonl", {"t": now(), "job": a.job, "outcome": "accepted" if a.accepted else "rejected", "note": a.note})
    g.save()
    print(json.dumps({"job": a.job, "outcome": "accepted" if a.accepted else "rejected", "edges_adjusted": n}))


def cmd_learn_captions(g, a):
    d = load_json(a.file, {}) or {}
    cl = f"client:{slug(a.client)}" if a.client else None
    n = 0
    for e in d.get("events", []):
        for i in e.get("emph", []):
            w = re.sub(r"\W+", "", e["words"][i].lower())
            if len(w) < 3 or w in STOP:
                continue
            g.node(f"word:{w}", w)
            g.edge(f"word:{w}", "motion:emphasis", "gets_motion", 0.15)
            if a.style:
                g.edge(f"style:{a.style}", f"word:{w}", "emphasises", 0.1)
            if cl:
                g.edge(cl, f"word:{w}", "emphasises", 0.1)
            n += 1
    g.node("motion:emphasis", "emphasis (big/accent word)")
    g.save()
    print(json.dumps({"emphasis_words_learned": n}))


def cmd_learn_cutplan(g, a):
    d = load_json(a.file, {}) or {}
    cl = f"client:{slug(a.client)}" if a.client else None
    kinds = defaultdict(int)
    for t in d.get("removed_tokens", []):
        kinds[t.get("reason", "other") if isinstance(t, dict) else "other"] += 1
    for reason, c in kinds.items():
        rid = f"cutreason:{slug(reason)}"
        g.node(rid, reason)
        g.edge(cl or "client:_all", rid, "often_removes", min(0.1 * c, 1.0))
    g.save()
    print(json.dumps(dict(kinds)))


def cmd_ingest_references(g, a):
    ws = find_workspace()
    sk = Path(__file__).resolve().parent.parent
    added = 0
    # presets -> technique, asset categories
    for p in sorted((ws / "presets").glob("*.json")):
        d = load_json(p, {}) or {}
        pid = f"preset:{d.get('id', p.stem)}"
        g.node(pid, d.get("id", p.stem), kind=d.get("kind"), confidence=d.get("confidence"))
        tq = d.get("technique")
        if tq:
            g.node(f"technique:{tq}", tq)
            g.edge(f"technique:{tq}", pid, "implemented_by", 1.0, reinforce=False)
        for cat in (d.get("assets") or {}).get("kinds", []):
            ac = f"asset_cat:{slug(cat)}"
            g.node(ac, cat)
            g.edge(pid, ac, "draws_on", 1.0, reinforce=False)
        for ref in re.findall(r"Video-\d+", d.get("source", "")):
            g.node(f"reference:{ref}", ref)
            g.edge(pid, f"reference:{ref}", "seen_in", 1.0, reinforce=False)
        added += 1
    # fingerprints -> reference -> techniques
    tech_by_ref = {}
    for p in sorted((ws / "style-fingerprints").glob("*.md")):
        txt = p.read_text(encoding="utf-8")
        ref = f"reference:{p.stem}"
        g.node(ref, p.stem)
        m = re.search(r"techniques\s+([T0-9 ]+)", txt)
        fam = re.search(r"Family \*\*(\w+)\*\*", txt)
        if fam:
            g.nodes[ref]["props"]["family"] = fam.group(1)
        tl = m.group(1).split() if m else []
        tech_by_ref[ref] = tl
        for t in tl:
            g.node(f"technique:{t}", t)
            g.edge(ref, f"technique:{t}", "shows", 1.0, reinforce=False)
    # techniques that co-occur in >= 2 references get a weak automatic co_occurs edge (a link a human may not notice)
    pair = defaultdict(int)
    for ts in tech_by_ref.values():
        for i, x in enumerate(ts):
            for y in ts[i + 1:]:
                pair[tuple(sorted((x, y)))] += 1
    auto = 0
    for (x, y), c in pair.items():
        if c >= 2:
            k = f"technique:{x}|co_occurs|technique:{y}"
            if k not in g.edges:
                g.edge(f"technique:{x}", f"technique:{y}", "co_occurs", min(0.3 * c, 2.0), auto=True)
                auto += 1
    # styles
    for p in sorted((ws / "styles").glob("*.json")):
        d = load_json(p, {}) or {}
        sid = f"style:{d['id']}"
        g.node(sid, d.get("name", d["id"]), family=d.get("family"), status=d.get("status"))
        for pr in d.get("presets", []):
            g.edge(sid, f"preset:{pr}", "uses_preset", 1.5, reinforce=False)
        for r in d.get("source_refs", []):
            g.node(f"reference:{r}", r)
            g.edge(sid, f"reference:{r}", "learned_from", 1.0, reinforce=False)
        for cat in (d.get("assets") or {}).get("categories", []):
            ac = f"asset_cat:{slug(cat)}"
            g.node(ac, cat)
            g.edge(sid, ac, "draws_on", 1.0, reinforce=False)
    g.save()
    print(json.dumps({"presets": added, "auto_links": auto, "nodes": len(g.nodes), "edges": len(g.edges)}))


def active_rules(g, client, style, job):
    rs = []
    for nid, n in g.nodes.items():
        if n["type"] == "rule" and n["props"].get("status", "active") == "active" and applies(n, client, style, job):
            spec = SCOPE_RANK[n["props"].get("scope", "global")]
            rs.append((spec, rule_eff(g, n), nid, n))
    rs.sort(key=lambda x: (-x[0], -x[1]))
    return rs


def cmd_overrides(g, a):
    out = {}
    for spec, w, nid, n in reversed(active_rules(g, a.client, a.style, a.job)):  # least specific first, specific wins
        if n["props"].get("polarity") == "do":
            out.update(n["props"].get("params", {}))
    print(json.dumps(out, indent=1))


def cmd_context(g, a):
    cl = f"client:{slug(a.client)}" if a.client else None
    st = f"style:{a.style}" if a.style else None
    words = [f"word:{slug(w)}" for w in (a.words or "").split() if slug(w) not in STOP]
    seeds = [s for s in [cl, st] + words if s]
    act = g.activate(seeds) if seeds else {}
    rules = active_rules(g, a.client, a.style, a.job)
    lines = ["# Editing memory (auto-generated, trust order: job > client > style > global)"]
    avoid = [r for r in rules if r[3]["props"].get("polarity") == "avoid"]
    do = [r for r in rules if r[3]["props"].get("polarity") != "avoid"]
    if avoid:
        lines.append("\n## NEVER / avoid")
        for spec, w, nid, n in avoid:
            lines.append(f"- [{n['props']['scope']}, x{n['props'].get('count', 1)}] {n['props']['text']}")
    if do:
        lines.append("\n## Standing instructions")
        for spec, w, nid, n in do:
            pr = n["props"].get("params")
            lines.append(f"- [{n['props']['scope']}, x{n['props'].get('count', 1)}] {n['props']['text']}"
                         + (f"  -> params {json.dumps(pr)}" if pr else ""))
    ov = {}
    for spec, w, nid, n in reversed(rules):
        if n["props"].get("polarity") == "do":
            ov.update(n["props"].get("params", {}))
    if ov:
        lines.append("\n## Parameter overrides (apply to scripts/presets)\n" + json.dumps(ov))

    def top(types, k, skip=()):
        c = [(v, nid) for nid, v in act.items() if g.nodes[nid]["type"] in types and nid not in seeds and nid not in skip]
        return sorted(c, reverse=True)[:k]
    sec = [("Presets that fit", {"preset"}, 6), ("Asset categories that fit", {"asset_cat"}, 5),
           ("Techniques", {"technique"}, 5), ("Learned motions for these words", {"motion"}, 6)]
    for title, types, k in sec:
        t = top(types, k)
        if t:
            lines.append(f"\n## {title}\n" + ", ".join(f"{g.nodes[n]['label']} ({v:.2f})" for v, n in t))
    ins = insights(g)
    warn = [i for i in ins if i["kind"] == "conflict"]
    if warn:
        lines.append("\n## Conflicts to resolve with the user\n" + "\n".join("- " + w["msg"] for w in warn[:3]))
    text = "\n".join(lines)
    budget = a.budget
    if len(text) > budget:
        text = text[:budget].rsplit("\n", 1)[0] + "\n... (truncated to budget; ask kb.py search for more)"
    print(text)


def insights(g):
    out = []
    rules = [(i, n) for i, n in g.nodes.items() if n["type"] == "rule" and n["props"].get("status") == "active"]
    for x in range(len(rules)):
        for y in range(x + 1, len(rules)):
            (i, a), (j, b) = rules[x], rules[y]
            pa, pb = a["props"], b["props"]
            if pa.get("polarity") != pb.get("polarity") and set(pa.get("targets", [])) & set(pb.get("targets", [])) \
                    and (pa.get("scope") == pb.get("scope")):
                out.append({"kind": "conflict", "nodes": [i, j], "msg": f"'{pa['text']}' vs '{pb['text']}' (same target)"})
    deg = defaultdict(float)
    for k, e in g.edges.items():
        a_, rel, b_ = k.split("|")
        deg[a_] += g.eff(e)
        deg[b_] += g.eff(e)
    for nid in g.nodes:
        if deg.get(nid, 0) == 0 and g.nodes[nid]["type"] not in ("job",):
            out.append({"kind": "orphan", "nodes": [nid], "msg": f"{nid} has no links"})
    hubs = sorted(deg.items(), key=lambda x: -x[1])[:5]
    out.append({"kind": "hubs", "nodes": [h for h, _ in hubs], "msg": "most connected: " + ", ".join(f"{h} ({w:.1f})" for h, w in hubs)})
    for k, e in g.edges.items():
        if e.get("auto") and e["n"] == 1 and e["w"] >= 0.6:
            out.append({"kind": "suggested-link", "nodes": k.split("|"), "msg": f"auto link {k} (co-occurs in references): confirm or delete"})
    return out


def cmd_show(g, a):
    n = g.nodes.get(a.node)
    if not n:
        raise SystemExit(f"no node {a.node}")
    nb = sorted(g.neighbours(a.node), key=lambda x: -x[2])[:25]
    print(json.dumps({"node": a.node, **n, "links": [{"to": b, "rel": r, "w": round(w, 2), "n": e["n"]} for b, r, w, e in nb]},
                     indent=1, ensure_ascii=False))


def cmd_search(g, a):
    q = a.text.lower()
    res = []
    for nid, n in g.nodes.items():
        hay = (nid + " " + n["label"] + " " + json.dumps(n["props"], ensure_ascii=False)).lower()
        if q in hay:
            res.append((n["w"], nid, n["label"]))
    for w, nid, lab in sorted(res, reverse=True)[:25]:
        print(nid, "|", lab)


def cmd_stats(g, a):
    c = defaultdict(int)
    for n in g.nodes.values():
        c[n["type"]] += 1
    print(json.dumps({"nodes": len(g.nodes), "edges": len(g.edges), "by_type": dict(c),
                      "feedback_logged": sum(1 for _ in open(g.dir / "feedback.jsonl", encoding="utf-8")) if (g.dir / "feedback.jsonl").exists() else 0}))


def cmd_export(g, a):
    L = ["# Editing knowledge (generated by kb.py export; edit via kb.py, not by hand)\n", f"_Updated {now()}_\n"]
    for scope in ("global", "style", "client", "job"):
        rs = [n for n in g.nodes.values() if n["type"] == "rule" and n["props"].get("scope") == scope
              and n["props"].get("status") == "active"]
        if rs:
            L.append(f"\n## Rules: {scope}")
            for n in sorted(rs, key=lambda n: -n["w"]):
                p = n["props"]
                who = p.get("client") or p.get("style") or p.get("job") or ""
                L.append(f"- ({p['polarity']}, x{p.get('count', 1)}) {who + ': ' if who else ''}{p['text']}"
                         + (f"  `{json.dumps(p['params'])}`" if p.get("params") else ""))
    L.append("\n## Strongest links")
    for k, e in sorted(g.edges.items(), key=lambda kv: -g.eff(kv[1]))[:40]:
        a_, rel, b_ = k.split("|")
        L.append(f"- {g.nodes[a_]['label']} --{rel}--> {g.nodes[b_]['label']}  ({g.eff(e):.2f}, n={e['n']})")
    L.append("\n## Insights")
    for i in insights(g)[:20]:
        L.append(f"- [{i['kind']}] {i['msg']}")
    (g.dir / "KNOWLEDGE.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(str(g.dir / "KNOWLEDGE.md"))


def cmd_sync(g, a):
    ws = find_workspace()
    cmd_export(g, a)
    subprocess.run(["git", "add", "knowledge"], cwd=ws, check=False)
    r = subprocess.run(["git", "commit", "-m", "Update editing knowledge graph"], cwd=ws, capture_output=True, text=True)
    print(r.stdout.strip() or r.stderr.strip())
    if a.push:
        p = subprocess.run(["git", "push"], cwd=ws, capture_output=True, text=True)
        print(p.stdout.strip() or p.stderr.strip())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    sub.add_parser("ingest-references")
    p = sub.add_parser("feedback")
    p.add_argument("--text", required=True)
    p.add_argument("--scope", choices=list(SCOPE_RANK), default="global")
    p.add_argument("--client"); p.add_argument("--style"); p.add_argument("--job")
    p.add_argument("--polarity", choices=["do", "avoid"], default="do")
    p.add_argument("--target", action="append"); p.add_argument("--param", action="append")
    p = sub.add_parser("decide")
    p.add_argument("--job", required=True)
    for f in ("client", "style", "word", "motion", "preset", "asset-cat", "note"):
        p.add_argument("--" + f)
    p = sub.add_parser("outcome")
    p.add_argument("--job", required=True)
    g_ = p.add_mutually_exclusive_group(required=True)
    g_.add_argument("--accepted", action="store_true"); g_.add_argument("--rejected", action="store_true")
    p.add_argument("--note")
    for name in ("learn-captions", "learn-cutplan"):
        p = sub.add_parser(name)
        p.add_argument("file"); p.add_argument("--job"); p.add_argument("--style"); p.add_argument("--client")
    p = sub.add_parser("context")
    p.add_argument("--client"); p.add_argument("--style"); p.add_argument("--job"); p.add_argument("--words")
    p.add_argument("--budget", type=int, default=2500)
    p = sub.add_parser("overrides")
    p.add_argument("--client"); p.add_argument("--style"); p.add_argument("--job")
    p = sub.add_parser("link")
    p.add_argument("a"); p.add_argument("b"); p.add_argument("--rel", required=True); p.add_argument("--w", type=float, default=1.0)
    p = sub.add_parser("show"); p.add_argument("node")
    p = sub.add_parser("search"); p.add_argument("text")
    sub.add_parser("insights"); sub.add_parser("stats"); sub.add_parser("export")
    p = sub.add_parser("sync"); p.add_argument("--push", action="store_true")
    a = ap.parse_args()
    g = Graph()
    if a.cmd == "init":
        g.save(); print(g.path); return
    if a.cmd == "link":
        print(g.edge(a.a, a.b, a.rel, a.w)); g.save(); return
    if a.cmd == "insights":
        for i in insights(g):
            print(f"[{i['kind']}] {i['msg']}")
        return
    if hasattr(a, "asset_cat"):
        a.asset_cat = getattr(a, "asset_cat")
    fn = {"feedback": cmd_feedback, "decide": cmd_decide, "outcome": cmd_outcome, "learn-captions": cmd_learn_captions,
          "learn-cutplan": cmd_learn_cutplan, "ingest-references": cmd_ingest_references, "context": cmd_context,
          "overrides": cmd_overrides, "show": cmd_show, "search": cmd_search, "stats": cmd_stats,
          "export": cmd_export, "sync": cmd_sync}[a.cmd]
    fn(g, a)


if __name__ == "__main__":
    main()

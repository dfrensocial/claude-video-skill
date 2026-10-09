# Knowledge base (the editing memory)

A local weighted graph that remembers what the user wants and what worked, so corrections are never repeated and the context window only carries what matters for the job at hand. Code: `scripts/kb.py`. Data: `<workspace>/knowledge/` (`graph.json`, `feedback.jsonl`, `decisions.jsonl`, `KNOWLEDGE.md`), plain JSON, committed to git.

## What is in it
| Node type | Examples | Where it comes from |
|---|---|---|
| style, preset, technique, asset_cat, reference | `style:yellow-infocard-tanglish`, `preset:word-pop-caption`, `technique:T7`, `asset_cat:glow-fx`, `reference:Video-86635` | `kb.py ingest-references` (reads `styles/`, `presets/`, `style-fingerprints/`) |
| client, job | `client:acme`, `job:acme-ad-01` | `decide`, `feedback` |
| rule | "captions bigger" scope=client, params `captions.scale=1.3`, polarity do/avoid | `kb.py feedback` from the user's own words |
| word, motion | `word:website -> motion:scale-pop` | `decide`, `learn-captions` |
| cutreason | fillers/retakes this client's footage keeps needing | `learn-cutplan` |
Edges are typed and weighted (`uses_preset`, `draws_on`, `gets_motion`, `prefers`, `co_occurs`, `rule_of`, `applies_to`, `avoids`...). Weights rise when a link is used or confirmed, fall on rejection, and decay with age (edges 180 d half-life, user rules 365 d, rules stated twice or more never drop below 25 %).

## When the agent calls it (this is the "loop")
1. **Job start**: `kb.py context --client X --style S --words "..."` (~2.5 k characters max): avoid-list first, then standing instructions with scope and how often the user said them, parameter overrides, the presets/asset categories that fit (spreading activation 2 hops from client + style + brief words), learned word->motion pairs, and conflicts to resolve. `kb.py overrides` gives only the merged parameters for scripts.
2. **During the job**: `kb.py decide` for meaningful choices (a motion for a word, a preset, an asset category). `style.py plan` already records its preset choices.
3. **Whenever the user asks for a change**: `kb.py feedback --text "<their exact words>" --scope client|style|global|job [--client X --style S --job J] [--polarity avoid] [--target preset:id ...] [--param key=value ...]`. Pick the narrowest scope that is true: "make THIS one faster" = job; "for Acme always..." = client; "in the yellow style..." = style; "never..." about everything = global. The same instruction again reinforces the same rule (count and weight go up) instead of duplicating; an opposite instruction on the same target supersedes the old rule. Precedence: job > client > style > global; user rules are hard constraints over learned associations.
4. **When a version is approved or rejected**: `kb.py outcome --job NAME --accepted|--rejected` strengthens or weakens every link that job used.
5. **After captions or a cut plan exist**: `kb.py learn-captions captions.json --client X --style S`, `kb.py learn-cutplan cut_plan.json --client X`.
6. **Housekeeping**: `kb.py insights` finds what a human may miss: conflicting rules, orphan nodes, the hub nodes, and automatic `co_occurs` links between techniques that appear together in several references (confirm or delete). `kb.py export` writes `knowledge/KNOWLEDGE.md` for humans; `kb.py sync [--push]` commits `knowledge/` only.

## Scripts that already read it
`style.py plan` drops presets the client said to avoid, applies parameter overrides, boosts styles the client has used, and logs its choices. Other scripts should read `kb.py overrides` for their parameters.

## Honest limits
- It learns only what is told to it or what the agent records; nothing runs in the background by itself. "Periodic" updating = the agent follows step 11 of the pipeline each job, and `sync` after each session. A scheduled routine could automate `kb.py sync --push` later (ask the user first).
- Word->motion learning is statistical co-occurrence from logged decisions, not understanding; it needs several jobs before it helps.
- Retrieval is graph-based tag/neighbour activation, not embeddings, so a synonym the graph has never seen will not match. Use `kb.py search` for fuzzy lookup.
- Design follows the research in editing-knowledge.md section 6 (typed weighted edges, recency x importance x relevance, user rules as hard constraints, feedback -> rule lifecycle). The draft/active confirmation step for rules is not implemented yet: every stated rule is active immediately.

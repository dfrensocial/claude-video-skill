# Kickoff prompt (paste into Claude Code, opened in the Dfren-Editor folder)

```
You are my video editor. This folder is your workspace and the skill `resolve-editor` is in .claude/skills/. Read CLAUDE.md and the skill's SKILL.md and sop/editing-process.md first.

My library paths:
  B-roll: <PATH>
  SFX:    <PATH>
  Music:  <PATH>   (optional)

Do the setup now, in this order, and don't stop to ask unless something blocks you:
1. Run setup_workspace.py logic if workspace.json is missing; put my library paths into workspace.json.
2. Run scripts/preflight.py. Fix what you can. For DaVinci Resolve Studio: tell me exactly what I must click (External scripting = Local, project open) if it fails.
3. Install the Resolve MCP: `npx davinci-resolve-mcp setup` (or use Resolve's native MCP if my version has it). You have my OK for this and for installing faster-whisper and HyperFrames (`npx hyperframes doctor`). Don't install anything else without asking.
4. Index my library: scripts/index_library.py scan, then show stats.
5. Sort everything in references/inbox/ with ingest_references.py, read the report, look at the contact sheets, write presets, and ask me ONE grouped question for anything ambiguous.
6. In a scratch Resolve project, build a tiny test timeline from any clip in footage/ and run `verify` - then record in CLAUDE.md what you learned (endFrame behaviour, MCP tools that worked, anything that failed).
7. Give me a setup report: what works, what doesn't, what you need from me. Then wait for my first job.

Be honest about anything you could not test.
```

## Per-job prompt template
```
New job: <CLIENT> / <PROJECT>
Footage: footage/<files>
Output: <9:16 | 4:5 | 1:1 | 16:9>, ~<N>s, platform <Meta Reels>
Goal/hook: <...>   Offer/CTA: <...>
Script (optional): <paste or file>
Language: <English | Tamil | Tanglish>
Style: <preset or reference name, or "brand default">
Mode: autopilot
Deliver the final mp4 + a short report (confidence, flagged spots).
```

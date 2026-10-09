# Motion-asset library (overlays, green screens, letters, LUTs)

`workspace.json > library.assets_paths` points at the studio's pack folder (currently `assets/asserss/`, 1,066 indexable files; ~16 GB, git-ignored). It is **not** B-roll and has **no SFX or music**. Index it with `python scripts/index_library.py scan --kinds assets`; search with
`index_library.py search --kind assets --q "glow burst" [--category glow] [--alpha] [--asset-type video|image|lut] --sheet jobs/NAME/assets/s1.jpg`
and LOOK at the sheet before using anything. Never modify or move originals (the library is read-only).

## How each file is classified (hints, confirm on the sheet)
Each index entry carries `category` (top folder, Google-Drive suffix stripped), `alpha` (real transparency: a pixel format with an alpha plane is only a hint, a frame is then checked for transparent pixels, because the GIF decoder reports `bgra` for opaque GIFs), and `blend`, decided from the **frame corners** (name tokens only as a fallback):
| `blend` | meaning | how to place in Resolve |
|---|---|---|
| `normal` | has alpha (ProRes 4444 .mov, PNG, WebP) | V3/V4 as is; scale-pop in/out |
| `screen` | black background | clip blend/Composite mode **Screen** (or Add); lowers cleanly over footage |
| `chroma-key` | green background | Delta Keyer / 3D keyer, then despill; check edge on a frame |
| `multiply` | white background | Composite mode **Multiply** |
| `plate` | opaque full-frame background (speed lines, motion backgrounds) | goes UNDER a floating card on V2, or between scenes |

## What is in the pack (from the scan) and what it is for
| Category (files) | Use | Typical technique (see reference-analysis.md) |
|---|---|---|
| Paper effects (492: 393 green-key, 51 alpha) | torn-paper letters, numbers, symbols, paper cut text | T2, T10 collage text |
| Animated Letters Pack (134 = 67 GIFs + 67 stills; **corrected: the GIFs are opaque plates, not transparent**) | animated alphabet / digits / symbols; use as a plate or key them | T2 kinetic type, T7 numbers |
| Emojis (86; 79 real alpha) / PNGs (72; 68 real alpha) / Memes (35) | stickers, people cut-outs, reaction memes | cutaway accents, T10 |
| Back grounds (67) / Motion Backgrounds (43) | loopable backgrounds (some black = screen, some full plates) | T4 info cards, T6 |
| 10 Speed Lines Anime Backgrounds (11 plates) | speed-lines background | T6 "2X SPEED" scene |
| Glow FX (10) / Overlays (4) / Film Burn Transitions (16 screen) | flashes, light leaks, film burn, grain | T11 transitions, grade finishing |
| Green Screen (19) | liquid/page-turn/camera-lens transitions, loaders, money, graphs, IG like animation | T11, T12, stat moments |
| Circles, Squares, and Lines (16; 14 alpha) / Dotted Line Animations (24) | connectors, callout lines, shape wipes | T9 highlight/callout |
| IG Animations (6), Hands (6), Money Animation (2) | Instagram UI (like/save/follow), hands, cash | social-proof and CTA beats |
| LUTs (21 .cube) | `CCC_LUT`, `PGS_Film (Standard) 01-20` | T15 look; install into Resolve's LUT folder, then `Refresh` |
| Safe Zone.png | the studio's Reels UI overlay | measured safe zone (platforms.md) |
| `pre set davincie effect/` | **.drfx macros** (MagicLetterboxV2, MagicZoomV3, MrAlexTech Ultimate Seamless), preset zips (zoom/shake, paper animator, snap captions, paper rip transitions, Maps pack, Neo Starter) and Resolve shortcuts | T3-T5, T13; install = user double-click / Resolve `File > Import` |

## SFX (library/sfx, not in assets/)
`workspace.json > library.sfx_paths` points at `library/sfx` (40 files): `generated/` = 10 kinds x 3 variants synthesised locally by `sfxgen.py` (whoosh, swish, pop, click, tick, hit, riser, ding, glitch, stamp; original, royalty-free, **checked by measurement only: I cannot hear them**), and `paper/` = the 10 WAVs from the user's "Paper SFX (Free Sound Pack) by MrJustinEdits" zip (extracted by listing the zip first; no code was run). `sfxplan.py` places them on events. Music: none yet; supply tracks (`music_paths`), `compose.py` ducks them under the voice.

## Hard rules for these files
1. **Do not run, unzip into the project, or install anything from `pre set davincie effect/` without the user's OK.** It contains `.exe` installers (Claude Setup, Bambu Studio) that are unrelated to editing and unpacked third-party zips/.drfx. List and describe, then ask.
2. Prefer alpha/PNG assets, then black-background `screen` assets, then green-key. Key quality varies: inspect the first, middle and last frame after keying.
3. Respect licences: these are packs from third-party creators (names appear in folders, e.g. `@brettfully`, MrJustinEdits, DylanJohn grain). They are for the user's own client work; do not redistribute or put them in a public repo (the folder is git-ignored for that reason).
4. Match asset frame rate/size to the timeline; never upscale a lower-res plate behind a face.
5. Log every asset used in `jobs/NAME/log` so a revision can swap it.
6. When the pack lacks something (e.g. SFX), say "not in library" and propose a generated or user-supplied alternative.

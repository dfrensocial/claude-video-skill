# Platform specs (verify before relying)

| Placement | Ratio | Size | Notes |
|---|---|---|---|
| Reels / Stories | 9:16 | 1080x1920 | **Measured from the studio's own overlay `assets/asserss/Safe Zone.png` (1080x1920):** top ~148 px blocked; bottom blocked from y~1522 (~398 px); right-hand button column blocked from x~927 for y 819-1920. **Safe text box: x 0-920, y 150-1520** (best: x 60-900, y 220-1450). Left edge is free. Prefer the studio overlay over generic numbers; re-measure if Meta changes the layout. |
| Feed | 4:5 | 1080x1350 | |
| Square | 1:1 | 1080x1080 | |
| Landscape | 16:9 | 1920x1080 | |

Delivery: H.264 High, yuv420p, AAC 48 kHz, 30 fps (match source), -14 LUFS integrated, true peak ≤ -1.5 dBTP, `+faststart`. Reels ads: best under 30-60 s with a hook in the first 3 s; captions on (many watch muted). Ad claims: nothing the brief doesn't support; respect Meta ad policies (no before/after health claims, no personal-attribute callouts).

Naming: `{client}_{project}_{ratio}_{WxH}_{version}.mp4`.

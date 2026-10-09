# Platform specs (verify before relying)

| Placement | Ratio | Size | Notes |
|---|---|---|---|
| Reels / Stories | 9:16 | 1080x1920 | keep key text inside the central area; approx. top 14 % (~270 px) and bottom 20-35 % (~380-670 px) are covered by UI - **approximate, verify against Meta's current guide** |
| Feed | 4:5 | 1080x1350 | |
| Square | 1:1 | 1080x1080 | |
| Landscape | 16:9 | 1920x1080 | |

Delivery: H.264 High, yuv420p, AAC 48 kHz, 30 fps (match source), -14 LUFS integrated, true peak ≤ -1.5 dBTP, `+faststart`. Reels ads: best under 30-60 s with a hook in the first 3 s; captions on (many watch muted). Ad claims: nothing the brief doesn't support; respect Meta ad policies (no before/after health claims, no personal-attribute callouts).

Naming: `{client}_{project}_{ratio}_{WxH}_{version}.mp4`.

# VidBot playlist monitor

Monitors the configured unlisted YouTube playlist, stores transcript-grounded summaries, and renders a static companion library.

## Commands

```bash
python3 scripts/scan_playlist.py
python3 scripts/merge_summary.py /path/to/summaries.json
python3 scripts/render_site.py
python3 -m unittest discover -s tests -v
```

`scan_playlist.py` writes `data/pending.json` but does **not** mark a video complete. A video is added to `data/state.json` only after a valid summary is merged, so failed transcript or model runs are retried.

The site deliberately includes `noindex,nofollow` because the source playlist is unlisted. “First detected” is used instead of claiming YouTube's exact playlist-addition timestamp, which is not available through the page/yt-dlp scan.

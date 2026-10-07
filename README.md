# VidBot playlist monitor

Monitors the configured unlisted YouTube playlist, stores transcript-grounded summaries, and renders a static companion library.

## Commands

```bash
python3 scripts/scan_playlist.py
python3 scripts/merge_summary.py /path/to/summaries.json
python3 scripts/render_site.py
python3 -m unittest discover -s tests -v
./scripts/deploy_pages.sh
```

The production site is `https://inspiretelapps.github.io/vidbot-library/`. After a successful summary merge and tests, `scripts/deploy_pages.sh` pushes `main` and publishes the clean `public/` subtree to `gh-pages`.

Automated scans run at 06:00, 12:00, and 20:30 Africa/Johannesburg time. The header refresh icon calls the rate-limited local trigger service (`scripts/manual_refresh_server.py`) through Tailscale Funnel and queues the same Hermes cron workflow; new-video digests are delivered to WhatsApp.

`scan_playlist.py` writes `data/pending.json` but does **not** mark a video complete. A video is added to `data/state.json` only after a valid summary is merged, so failed transcript or model runs are retried.

## One-minute summaries

Summary generation happens outside this repository; the importer validates the supplied JSON. Include `quick_takeaways` in new summaries: up to six distinct, transcript-grounded points totaling at most 200 words. The site displays these directly on the video card instead of the "Why this is valuable" pitch. Older entries without this field retain their existing introduction.

Write the useful information itself: the recommendation, steps, results, specific tools, costs and material limits. Lead with the most consequential points. Each point should make sense without watching the video; omit teasers, statements about why to watch, promotional filler and repeated caveats. Attribute reported prices and claims when needed, and distinguish a demonstrated result from a proposal. Keep the longer `summary`, `key_takeaways` and `chapters` for depth and verification.

Do not include video timestamps in the executive `summary`; keep them in `chapters` for jump links. The importer, publication renderer and browser remove video-position annotations from executive summaries, including headings such as `Topic — 00:54–06:23`. Publication and display apply this rule even when a generator writes directly to the library. Section headings and meaningful references such as scheduled times or scripture citations remain intact.

The site deliberately includes `noindex,nofollow` because the source playlist is unlisted. “First detected” is used instead of claiming YouTube's exact playlist-addition timestamp, which is not available through the page/yt-dlp scan.

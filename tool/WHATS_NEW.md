# What's new

- **Window (Windows):** double-click `Contact Sheet.bat`. Shows every clip with its thumbnail and status
  (on YouTube / archived to Google Drive / waiting / failed). Buttons preview and start an upload or a Drive
  archive. It asks before anything runs. It never edits `manifest.csv` itself.
- **Phone page (home network only):** `py -3 clip_web.py` prints a link with a random token. Open it on a phone on
  the same Wi-Fi. You press Preview, read exactly what would happen, type UPLOAD or ARCHIVE, then confirm. It listens
  only on your private LAN address, never on the internet. Do not expose it publicly without a tunnel and a real login
  (for example Cloudflare Tunnel with Access).
- **`--yes` flag:** `clip_pipeline.py upload --yes` and `archive --yes` run without questions (used by the window and
  the phone page). It never bypasses the safeguards: uploads stay unlisted, `publish` always needs a person typing
  PUBLISH, and a sign-in that needs a browser is refused instead of opened.
- **Drive archive:** `clip_pipeline.py archive` copies clips that are on YouTube to Google Drive and checks each copy
  by MD5. It only copies: it never deletes or moves anything. Dropped connections are retried and resumed.
- Windows PowerShell 5.1 and Python 3 are all the window needs. No tracking, no third-party scripts.

Provided as is, without warranty.

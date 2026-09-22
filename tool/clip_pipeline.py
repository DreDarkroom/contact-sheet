#!/usr/bin/env python3
"""
Contact Sheet
=============
A small pipeline for VR/headset creators: Meta Quest gallery  ->  renamed local files  ->  YouTube (UNLISTED)

github.com/DreDarkroom/contact-sheet

Commands (normally you just double-click the .bat files):
    run       fetch new clips, ask what to leave out, rename, confirm, upload unlisted  (default)
    fetch     only fetch + rename new clips into the "new" folder (no upload)
    upload    only upload whatever is in the "new" folder (use after editing)
    publish   change an uploaded video from unlisted to public (asks you to confirm)

Options:
    --dry-run       show what would happen; download and upload nothing
    --since DATE    only look at gallery clips on/after DATE (YYYY-MM-DD)

Safety rules built in:
    * Uploads are ALWAYS unlisted. Only the "publish" command can change that.
    * The reference video's description must contain the required notice text, otherwise
      the upload stops (so a clip can never go up without the "unlisted" message).
    * The script never clicks anything in the Meta gallery except reading it; it downloads
      the video files directly and never uses the delete or select buttons.
"""

import argparse
import csv
import datetime as dt
import html
import json
import re
import sys
import time
import webbrowser
from pathlib import Path

BASE = Path(__file__).resolve().parent
CONFIG_PATH = BASE / "config.json"
DIR_NEW = BASE / "new"
DIR_UPLOADED = BASE / "uploaded"
DIR_PROFILE = BASE / "profile"
DIR_SECRETS = BASE / "secrets"
MANIFEST_PATH = BASE / "manifest.csv"
LOG_PATH = BASE / "pipeline.log"
REVIEW_HTML = BASE / "review.html"

DEFAULTS = {
    "gallery_url": "https://www.meta.com/gallery/",
    "browser_channel": "chrome",          # "chrome" = your installed Chrome; "" = Playwright's own Chromium
    "headless": False,                    # keep False so you can see the window / sign in
    "name_prefix": "MyClips",
    "since_date": "",                     # YYYY-MM-DD; empty = use lookback_days
    "lookback_days": 3,
    "min_duration_seconds": 30,           # clips shorter than this are ignored (accidental recordings)
    "gallery_order": "newest_first",      # order of clips within a day in the Meta gallery
    "reference_video_id": "",
    "required_description_text": "Unlisted video may only be shared if you gain permission first.",
    "title_suffix": "",
    "max_title_length": 100,
}

FIELDS = ["key", "date", "nn", "filename", "duration_s", "status",
          "youtube_id", "title", "updated", "note"]

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
DATE_RE = re.compile(r"^(\d{1,2})\s+([A-Za-z]{3,9})\.?\s+(\d{4})$")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"

# --------------------------------------------------------------------------- helpers


def log(msg):
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    print(msg)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_config():
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    return cfg


def ensure_dirs():
    for d in (DIR_NEW, DIR_UPLOADED, DIR_PROFILE, DIR_SECRETS):
        d.mkdir(parents=True, exist_ok=True)


def parse_gallery_date(text, today=None):
    """'19 Sept 2026' -> date(2026, 9, 19). Also understands Today / Yesterday."""
    if not text:
        return None
    today = today or dt.date.today()
    t = text.strip()
    if t.lower() == "today":
        return today
    if t.lower() == "yesterday":
        return today - dt.timedelta(days=1)
    m = DATE_RE.match(t)
    if not m:
        return None
    mon = MONTHS.get(m.group(2)[:3].lower())
    if not mon:
        return None
    try:
        return dt.date(int(m.group(3)), mon, int(m.group(1)))
    except ValueError:
        return None


def make_title(stem, suffix="", maxlen=100):
    """File name -> YouTube title. Letters, numbers and single spaces only."""
    text = f"{stem} {suffix}".strip()
    text = re.sub(r"[^A-Za-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:maxlen].strip()


def clip_key(src):
    """Stable ID for a gallery clip, taken from its video file name in the URL."""
    m = re.search(r"/([^/?#]+?)\.mp4", src)
    if m:
        return m.group(1)
    return "url:" + re.sub(r"[?#].*$", "", src)[-60:]


def fmt_duration(sec):
    if sec is None:
        return "??:??"
    sec = int(round(sec))
    return f"{sec // 60:02d}:{sec % 60:02d}"


def load_manifest():
    if not MANIFEST_PATH.exists():
        return []
    with open(MANIFEST_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_manifest(rows):
    tmp = MANIFEST_PATH.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})
    tmp.replace(MANIFEST_PATH)


def upsert(rows, key, **values):
    for r in rows:
        if r["key"] == key:
            r.update(values)
            r["updated"] = dt.datetime.now().isoformat(timespec="seconds")
            return r
    r = {k: "" for k in FIELDS}
    r.update(values)
    r["key"] = key
    r["updated"] = dt.datetime.now().isoformat(timespec="seconds")
    rows.append(r)
    return r


def highest_used(prefix, date_str, rows):
    """Highest clip number already used for this date (manifest + both folders)."""
    pat = re.compile(rf"^{re.escape(prefix)}_{date_str}_(\d+)\.mp4$")
    names = [r.get("filename", "") for r in rows]
    names += [p.name for p in DIR_NEW.glob("*.mp4")]
    names += [p.name for p in DIR_UPLOADED.glob("*.mp4")]
    used = 0
    for n in names:
        m = pat.match(n)
        if m:
            used = max(used, int(m.group(1)))
    return used


def assign_names(clips, cfg, rows):
    """clips are in gallery order. Numbers go oldest-first within each day."""
    by_date = {}
    for c in clips:
        by_date.setdefault(c["date"], []).append(c)
    for d, group in by_date.items():
        ordered = list(reversed(group)) if cfg["gallery_order"] == "newest_first" else list(group)
        date_str = d.strftime("%y%m%d")
        start = highest_used(cfg["name_prefix"], date_str, rows)
        for i, c in enumerate(ordered, 1):
            c["nn"] = start + i
            c["filename"] = f"{cfg['name_prefix']}_{date_str}_{start + i:02d}.mp4"
    return clips


# --------------------------------------------------------------------------- gallery reading

EXTRACT_JS = """
() => {
  const root = document.querySelector('main') || document.body;
  const dateRe = /^(\\d{1,2}\\s+[A-Za-z]{3,9}\\.?\\s+\\d{4}|Today|Yesterday)$/;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
  let date = null; const items = []; let n;
  while ((n = walker.nextNode())) {
    if (n.nodeType === 3) {
      const t = n.nodeValue.trim();
      if (dateRe.test(t)) date = t;
    } else if (n.tagName === 'VIDEO') {
      items.push({date: date, src: n.currentSrc || n.src || '', poster: n.poster || '',
                  dur: Number.isFinite(n.duration) ? n.duration : null, idx: items.length});
    }
  }
  return items;
}
"""

SCROLL_TO_JS = """
(i) => { const root = document.querySelector('main') || document.body;
         const v = root.querySelectorAll('video')[i]; if (v) v.scrollIntoView({block: 'center'}); }
"""


def open_browser(p, cfg):
    kwargs = dict(user_data_dir=str(DIR_PROFILE), headless=bool(cfg.get("headless", False)),
                  viewport={"width": 1280, "height": 900})
    if cfg["browser_channel"]:
        kwargs["channel"] = cfg["browser_channel"]
    return p.chromium.launch_persistent_context(**kwargs)


def ensure_signed_in(page, cfg):
    from playwright.sync_api import TimeoutError as PWTimeout
    for _ in range(2):
        try:
            page.wait_for_selector("video", timeout=25000)
            return True
        except PWTimeout:
            pass
        input("\nMeta may need you to sign in. Sign in in the browser window and open the Gallery,\n"
              "then press Enter here to carry on... ")
        page.goto(cfg["gallery_url"], wait_until="domcontentloaded")
    return page.query_selector("video") is not None


def read_gallery(page, since):
    """Scroll until clips older than `since` are loaded, then return every clip found."""
    last_count, stagnant = 0, 0
    for _ in range(80):
        items = page.evaluate(EXTRACT_JS)
        dates = [parse_gallery_date(i["date"]) for i in items if i["date"]]
        dates = [d for d in dates if d]
        if dates and min(dates) < since:
            break
        stagnant = stagnant + 1 if len(items) == last_count else 0
        if stagnant >= 3:
            break
        last_count = len(items)
        page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
        page.wait_for_timeout(1500)
    items = page.evaluate(EXTRACT_JS)
    for _ in range(3):  # some tiles only get their video address once they are on screen
        missing = [i for i in items if not i["src"]]
        if not missing:
            break
        for it in missing:
            page.evaluate(SCROLL_TO_JS, it["idx"])
            page.wait_for_timeout(700)
        items = page.evaluate(EXTRACT_JS)
    return items


def download(url, dest, cookies=None):
    import requests
    tmp = dest.with_suffix(".part")
    with requests.get(url, stream=True, timeout=(15, 120), headers={"User-Agent": UA},
                      cookies=cookies) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or 0)
        got, shown = 0, 0
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
                got += len(chunk)
                if got - shown >= 20 * (1 << 20):
                    shown = got
                    print(f"\r    {got // (1 << 20)} / {total // (1 << 20) if total else '?'} MB", end="", flush=True)
    print("\r" + " " * 40 + "\r", end="")
    if got == 0 or (total and got != total):
        tmp.unlink(missing_ok=True)
        raise IOError(f"incomplete download ({got} of {total} bytes)")
    tmp.replace(dest)
    return got


def write_review_page(clips):
    cards = []
    for n, c in enumerate(clips, 1):
        poster = html.escape(c.get("poster", ""))
        img = f'<img src="{poster}" alt="">' if poster else '<div class="noimg">no preview</div>'
        cards.append(
            f'<div class="card"><div class="num">{n}</div>{img}'
            f'<div class="meta">{c["date"]:%d %b %Y} &middot; {fmt_duration(c["dur"])}<br>'
            f'<small>{html.escape(c["filename"])}</small></div></div>')
    page = ("<!doctype html><meta charset='utf-8'><title>New clips</title>"
            "<style>body{font-family:sans-serif;background:#111;color:#eee;margin:20px}"
            ".grid{display:flex;flex-wrap:wrap;gap:14px}.card{width:260px;background:#222;border-radius:8px;"
            "position:relative;padding-bottom:8px}.card img,.noimg{width:100%;height:146px;object-fit:cover;"
            "border-radius:8px 8px 0 0;background:#333}.noimg{display:flex;align-items:center;justify-content:center}"
            ".num{position:absolute;top:6px;left:6px;background:#c00;color:#fff;font-weight:bold;"
            "border-radius:50%;width:30px;height:30px;text-align:center;line-height:30px}"
            ".meta{padding:8px 10px}small{color:#aaa}</style>"
            "<h2>New clips found - type the numbers you want to LEAVE OUT in the black window</h2>"
            f"<div class='grid'>{''.join(cards)}</div>")
    REVIEW_HTML.write_text(page, encoding="utf-8")


# --------------------------------------------------------------------------- fetch phase


def do_fetch(cfg, since, dry_run):
    from playwright.sync_api import sync_playwright
    rows = load_manifest()
    known = {r["key"] for r in rows}
    today = dt.date.today()

    with sync_playwright() as p:
        ctx = open_browser(p, cfg)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            log("Opening the Meta gallery...")
            page.goto(cfg["gallery_url"], wait_until="domcontentloaded")
            if not ensure_signed_in(page, cfg):
                log("No videos found in the gallery (or sign-in did not finish). Nothing to do.")
                return
            items = read_gallery(page, since)

            clips, short = [], 0
            for it in items:
                d = parse_gallery_date(it["date"], today)
                if not d or d < since or not it["src"]:
                    continue
                key = clip_key(it["src"])
                if key in known:
                    continue
                if it["dur"] is not None and it["dur"] < cfg["min_duration_seconds"]:
                    short += 1
                    continue
                clips.append({"key": key, "date": d, "src": it["src"], "poster": it["poster"],
                              "dur": it["dur"], "order": len(clips)})
            if short:
                log(f"Ignoring {short} clip(s) shorter than {cfg['min_duration_seconds']} seconds.")
            if not clips:
                log("No new clips found since " + since.isoformat() + ".")
                return

            assign_names(clips, cfg, rows)
            clips = sorted(clips, key=lambda c: (c["date"], c["nn"]))
            write_review_page(clips)
            print(f"\nFound {len(clips)} new clip(s):\n")
            for n, c in enumerate(clips, 1):
                print(f"  {n:2d}  {c['date']:%d %b %Y}  {fmt_duration(c['dur'])}  ->  {c['filename']}")
            if dry_run:
                print("\n(dry run: nothing downloaded)")
                return
            try:
                webbrowser.open(REVIEW_HTML.as_uri())
                print("\nA picture sheet of these clips has opened in your browser.")
            except Exception:
                pass
            ans = input("\nType the numbers to LEAVE OUT (for example 2,5) and press Enter,\n"
                        "or just press Enter to keep them all (type 'quit' to stop): ").strip().lower()
            if ans == "quit":
                return
            skip = {int(x) for x in re.findall(r"\d+", ans)}
            kept = []
            for n, c in enumerate(clips, 1):
                if n in skip:
                    upsert(rows, c["key"], date=c["date"].isoformat(), status="ignored",
                           duration_s=fmt_duration(c["dur"]), note="left out by user")
                else:
                    kept.append(c)
            save_manifest(rows)
            if not kept:
                log("Nothing left to download.")
                return
            kept.sort(key=lambda c: c["order"])  # back to gallery order before renumbering
            assign_names(kept, cfg, rows)  # renumber after leaving clips out

            cookies = None
            for c in kept:
                dest = DIR_NEW / c["filename"]
                log(f"Downloading {c['filename']} ...")
                try:
                    try:
                        size = download(c["src"], dest)
                    except Exception as e:
                        resp = getattr(e, "response", None)
                        if resp is not None and resp.status_code in (401, 403):
                            cookies = {ck["name"]: ck["value"] for ck in ctx.cookies(c["src"])}
                            size = download(c["src"], dest, cookies=cookies)
                        else:
                            raise
                    upsert(rows, c["key"], date=c["date"].isoformat(), nn=c["nn"],
                           filename=c["filename"], duration_s=fmt_duration(c["dur"]),
                           status="fetched", note=f"{size} bytes")
                    log(f"  saved ({size // (1 << 20)} MB)")
                except Exception as e:
                    upsert(rows, c["key"], date=c["date"].isoformat(), filename=c["filename"],
                           status="failed", note=str(e)[:200])
                    log(f"  FAILED: {e}")
                save_manifest(rows)
        finally:
            ctx.close()


# --------------------------------------------------------------------------- YouTube


def get_youtube():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    scopes = ["https://www.googleapis.com/auth/youtube"]
    token_path = DIR_SECRETS / "token.json"
    secret_path = DIR_SECRETS / "client_secret.json"
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception:
            creds = None
    if not creds or not creds.valid:
        if not secret_path.exists():
            raise SystemExit("Missing secrets\\client_secret.json - see step 4 of SETUP_GUIDE.md")
        flow = InstalledAppFlow.from_client_secrets_file(str(secret_path), scopes)
        print("\nA browser window will open so you can sign in to YouTube and allow uploads...")
        creds = flow.run_local_server(port=0)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=creds)


def reference_details(yt, cfg):
    """Copy description, tags and settings from the reference video (everything except the title)."""
    vid = cfg["reference_video_id"].strip()
    if not vid:
        raise SystemExit("Set reference_video_id in config.json first.")
    items = yt.videos().list(part="snippet,status", id=vid).execute().get("items", [])
    if not items:
        raise SystemExit("Reference video not found. Check reference_video_id and that you signed in "
                         "with the YouTube account that owns it.")
    sn, st = items[0]["snippet"], items[0]["status"]
    desc = sn.get("description", "")
    need = cfg["required_description_text"]
    if need and need.lower() not in desc.lower():
        raise SystemExit("The reference video's description does not contain the required notice:\n"
                         f'  "{need}"\nAdd it in YouTube Studio first, then run again. Nothing was uploaded.')
    snippet = {"description": desc, "tags": sn.get("tags", []), "categoryId": sn.get("categoryId", "20")}
    for k in ("defaultLanguage", "defaultAudioLanguage"):
        if sn.get(k):
            snippet[k] = sn[k]
    status = {"privacyStatus": "unlisted",  # hard-coded on purpose
              "selfDeclaredMadeForKids": st.get("selfDeclaredMadeForKids", False)}
    for k in ("license", "embeddable", "publicStatsViewable"):
        if k in st:
            status[k] = st[k]
    return snippet, status


def upload_phase(cfg, dry_run, assume_yes=False):
    files = sorted(DIR_NEW.glob("*.mp4"))
    if not files:
        log("Nothing in the 'new' folder to upload.")
        return
    print(f"\nReady to upload {len(files)} clip(s) as UNLISTED:\n")
    titles = {}
    for f in files:
        titles[f] = make_title(f.stem, cfg["title_suffix"], cfg["max_title_length"])
        print(f"  {f.name}\n      title: {titles[f]}   ({f.stat().st_size // (1 << 20)} MB)")
    if dry_run:
        print("\n(dry run: nothing uploaded)")
        return
    if not assume_yes:
        ans = input("\nUpload these now? Press Enter for yes, or type n to keep them in the 'new' folder "
                    "(for example to edit them first): ").strip().lower()
        if ans.startswith("n"):
            print("OK - they stay in the 'new' folder. Run 'Upload New Clips' again when ready.")
            return

    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload
    yt = get_youtube()
    snippet, status = reference_details(yt, cfg)
    rows = load_manifest()
    by_name = {r.get("filename"): r for r in rows}

    for f in files:
        title = titles[f]
        log(f"Uploading {f.name} ...")
        body = {"snippet": {**snippet, "title": title}, "status": dict(status)}
        media = MediaFileUpload(str(f), chunksize=8 * 1024 * 1024, resumable=True, mimetype="video/mp4")
        request = yt.videos().insert(part="snippet,status", body=body, media_body=media)
        response, tries = None, 0
        try:
            while response is None:
                try:
                    prog, response = request.next_chunk()
                    if prog:
                        print(f"\r    {int(prog.progress() * 100)}%", end="", flush=True)
                except HttpError as e:
                    if e.resp.status in (500, 502, 503, 504) and tries < 5:
                        tries += 1
                        time.sleep(2 ** tries)
                        continue
                    raise
            print("\r    100%")
        except HttpError as e:
            text = str(e)
            log(f"  FAILED: {text[:300]}")
            if "uploadLimitExceeded" in text or "quotaExceeded" in text:
                log("YouTube's daily upload limit has been reached. Try again tomorrow.")
                return
            continue
        vid = response["id"]
        final = response.get("status", {}).get("privacyStatus", "?")
        log(f"  done: https://youtu.be/{vid}  (visibility: {final})")
        if final != "unlisted":
            log("  !! YouTube set this video to '" + final + "', not unlisted. This happens when the Google\n"
                "     Cloud project has not passed YouTube's API audit. Set it to Unlisted in YouTube Studio\n"
                "     (see SETUP_GUIDE.txt, section 'If uploads come out private').")
        target = DIR_UPLOADED / f.name
        f.replace(target)
        row = by_name.get(f.name)
        key = row["key"] if row else "file:" + f.name
        upsert(rows, key, filename=f.name, status="uploaded", youtube_id=vid, title=title,
               note=f"visibility {final}")
        save_manifest(rows)


def publish_phase(cfg):
    rows = [r for r in load_manifest() if r.get("status") == "uploaded" and r.get("youtube_id")]
    if not rows:
        print("No uploaded videos recorded yet.")
        return
    yt = get_youtube()
    ids = [r["youtube_id"] for r in rows][-50:]
    live = {v["id"]: v for v in yt.videos().list(part="snippet,status", id=",".join(ids)).execute()["items"]}
    shown = [r for r in rows if r["youtube_id"] in live][-50:]
    print("\nYour uploaded videos:\n")
    for n, r in enumerate(shown, 1):
        v = live[r["youtube_id"]]
        print(f"  {n:2d}  {v['snippet']['title']}   [{v['status']['privacyStatus']}]   https://youtu.be/{r['youtube_id']}")
    ans = input("\nNumber of the video to change (Enter to cancel): ").strip()
    if not ans.isdigit() or not (1 <= int(ans) <= len(shown)):
        print("Cancelled.")
        return
    r = shown[int(ans) - 1]
    v = live[r["youtube_id"]]
    target = input("Change it to public / unlisted / private? [public]: ").strip().lower() or "public"
    if target not in ("public", "unlisted", "private"):
        print("Cancelled.")
        return
    if target == "public":
        print(f"\nThis makes '{v['snippet']['title']}' visible to everyone.")
        if input("Type PUBLISH to confirm: ").strip() != "PUBLISH":
            print("Cancelled - nothing changed.")
            return
    st = v["status"]
    new_status = {"privacyStatus": target}
    for k in ("license", "embeddable", "publicStatsViewable", "selfDeclaredMadeForKids"):
        if k in st:
            new_status[k] = st[k]
    yt.videos().update(part="status", body={"id": r["youtube_id"], "status": new_status}).execute()
    log(f"{r['youtube_id']} is now {target}.")


# --------------------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser(description="Contact Sheet - Meta Quest gallery pipeline")
    ap.add_argument("command", nargs="?", default="run", choices=["run", "fetch", "upload", "publish"])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--since", help="YYYY-MM-DD")
    args = ap.parse_args()

    cfg = load_config()
    ensure_dirs()

    since_text = args.since or cfg["since_date"]
    if since_text:
        since = dt.date.fromisoformat(since_text)
    else:
        since = dt.date.today() - dt.timedelta(days=int(cfg["lookback_days"]))

    try:
        if args.command in ("run", "fetch"):
            do_fetch(cfg, since, args.dry_run)
        if args.command in ("run", "upload"):
            upload_phase(cfg, args.dry_run)
        if args.command == "publish":
            publish_phase(cfg)
    except KeyboardInterrupt:
        print("\nStopped.")
    print("\nAll done.")


if __name__ == "__main__":
    main()

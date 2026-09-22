# Contact Sheet — setup guide

## What it does

After a recording session, run `Upload New Clips`. It:

1. opens your Meta gallery in its own Chrome window and finds clips it hasn't seen before,
2. shows you a picture sheet so you can leave out the ones you don't want (other content, accidents),
3. downloads the rest and renames them cleanly, e.g. `MyClips_260919_02.mp4`,
4. shows you the YouTube titles it will use and asks you to confirm,
5. uploads them to YouTube as **UNLISTED**, copying the description, tags and settings from a reference video you choose.

It never makes anything public on its own. That's a separate step (`publish`) that asks you to type `PUBLISH`.

The title is the file name with underscores turned into spaces and every symbol stripped, so
`MyClips_260919_02.mp4` becomes: `MyClips 260919 02`. Pick a `name_prefix` in `config.json`
that means something to you — it never has to say what the footage is of.

## One-time setup (about 20–30 minutes)

### 1. Python

Check first: open a terminal and run `python3 --version` (or `py --version` on Windows).
If it prints 3.9 or newer, skip to step 2. Otherwise install Python from
https://www.python.org/downloads/ — on Windows, tick "Add python.exe to PATH" during install.

### 2. Install the dependencies

```
pip install playwright requests google-auth-oauthlib google-api-python-client
playwright install chromium
```

### 3. Pick a reference video

Upload (or reuse) one YouTube video whose description contains the exact notice text you want
copied onto every future upload — by default that's:

> Unlisted video may only be shared if you gain permission first.

The script checks for this text and refuses to upload if it's missing, so a clip can never go
out without your notice attached. Set `reference_video_id` in `config.json` to that video's ID
(the part after `youtu.be/`).

### 4. Let the script talk to YouTube (Google Cloud, free)

This gives the script permission to upload on your behalf. Google's menu names shift over time,
so the wording below may drift slightly.

1. Go to https://console.cloud.google.com/ and sign in with the account that owns your YouTube channel.
2. Project picker → New Project → name it anything → Create.
3. Menu → APIs & Services → Library → search "YouTube Data API v3" → Enable.
4. Menu → APIs & Services → OAuth consent screen. User type: External. Fill in an app name and
   your email. Under "Test users" add your own Google email address.
5. Menu → APIs & Services → Credentials → Create credentials → OAuth client ID →
   Application type: Desktop app → Create → Download JSON.
6. Rename the downloaded file to `client_secret.json` and put it in the `secrets/` folder next
   to the script.

On first upload, Google will warn "this app isn't verified" — that's expected for your own
private app: Advanced → Go to [your app name] (unsafe) → allow. Never share `client_secret.json`
or the `token.json` that appears next to it afterwards.

While the consent screen is in "Testing" mode, sign-in expires after 7 days. The script just
reopens the Google sign-in page when that happens — nothing breaks.

### 5. First run

Run `python clip_pipeline.py run`. A Chrome window opens on your Meta gallery. Sign in if asked
(it remembers you afterwards). By default it only looks at clips from the last 3 days — change
`since_date` or `lookback_days` in `config.json` to go further back.

## Everyday use

```
python clip_pipeline.py run       # fetch, rename, confirm, upload unlisted
python clip_pipeline.py publish   # pick an uploaded video and make it public (types PUBLISH)
python clip_pipeline.py upload    # upload whatever is already in the "new" folder, no fetch
```

### Editing before upload

When it asks "Upload these now?", type `n`. The clips stay in the `new/` folder — edit them
(keep the same file name) and run `python clip_pipeline.py upload` when ready.

### Folders

| Folder | What's in it |
|---|---|
| `new/` | clips downloaded and renamed, waiting for upload |
| `uploaded/` | clips already on YouTube |
| `profile/` | the Chrome sign-in for Meta (never share this) |
| `secrets/` | your Google files (never share this) |
| `manifest.csv` | every clip: date, number, YouTube ID, status |
| `pipeline.log` | what happened on each run |

### Settings in `config.json`

| Setting | Meaning |
|---|---|
| `since_date` | only clips on/after this date (`YYYY-MM-DD`); blank = use `lookback_days` |
| `min_duration_seconds` | clips shorter than this are ignored (accidental recordings) |
| `name_prefix` | start of every file name — make it your own |
| `title_suffix` | text appended to every YouTube title |
| `gallery_order` | whether your Meta gallery lists newest or oldest clip first within a day |
| `reference_video_id` | the video whose description/tags/settings get copied |

## If uploads come out private instead of unlisted

Google locks API uploads from unaudited projects to private. The script will tell you if this
happens. Options:

- Open YouTube Studio, select the video, set Visibility to Unlisted yourself, or
- Apply for Google's API audit ("YouTube API Services - Audit and Quota Extension Form").

Either way, the script still saves you the downloading, renaming, titling and description work.

## Honest limits

- Built and tested against a real Meta gallery, but Meta's page layout can change without notice
  — if a run fails, the error message in the terminal is the place to start.
- The gallery doesn't tag which project/content a clip is from. The picture-sheet step is how you
  leave clips out; once left out, a clip is remembered and never asked about again.
- Clip numbering within a day assumes the gallery lists the newest clip first. If numbers come out
  backwards, set `gallery_order` to `"oldest_first"`.
- Uploads use your normal YouTube daily upload allowance.
- Nothing about your account, your gallery, or your footage leaves your machine except the actual
  video files you choose to upload.

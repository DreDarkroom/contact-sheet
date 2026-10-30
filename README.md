# Contact Sheet

A small pipeline for VR/headset creators: pull new clips and stills off your **Meta Quest gallery**,
give them clean consistent names, and get them ready to publish — clips go to **YouTube as unlisted**
until you say otherwise, stills go to your own cloud storage. Built because doing this by hand,
clip after clip, got old fast.

**[See it explained →](https://dredarkroom.github.io/contact-sheet/)**

## What it does

1. Finds clips in your Meta gallery it hasn't seen before.
2. Shows you a picture sheet so you can leave out the ones you don't want.
3. Renames the rest with a clean, consistent, date-based convention you control.
4. Uploads to YouTube as **unlisted** — always, with a hard-coded safety check that refuses to
   upload if your chosen notice text isn't present on the reference video's description.
5. A separate, deliberate `publish` step (types `PUBLISH` to confirm) is the only way anything
   goes public.
6. Optional: archives clips that are on YouTube to your Google Drive, copying only and checking each copy by MD5 (nothing is ever deleted).

Still images aren't a YouTube fit, so this repo also documents the lighter-weight side pipeline:
pulling gallery photos and handing them to whatever cloud storage syncs on your machine (Dropbox,
OneDrive, etc.) instead.

## Window and phone page

- **Windows:** double-click `tool/Contact Sheet.bat` for a small dark window with thumbnails, status, and buttons to preview and start an upload or a Drive archive. It asks first.
- **Phone (home Wi-Fi only):** `py -3 clip_web.py` prints a link with a random token. Preview, type a confirmation word, then confirm. It is not exposed to the internet; put it behind a tunnel with a real login before ever changing that.
- **`--yes`:** non-interactive runs for the above. It never bypasses the safeguards: uploads stay unlisted and `publish` always needs a person typing `PUBLISH`.

See [`tool/WHATS_NEW.md`](tool/WHATS_NEW.md).

## Why

Meta's gallery has no public download API and no bulk "send to YouTube" option. Doing this by hand
— find the clip, work out what to call it, download it, retitle it, set visibility, write a
description — for every single recording session doesn't scale. This does the boring parts and
leaves every judgment call (what to keep, when to go public) to you.

## Get started

See [`tool/SETUP_GUIDE.md`](tool/SETUP_GUIDE.md). Twenty to thirty minutes, entirely free
(uses Google's free YouTube Data API tier), runs on Python + your own Chrome.

## Status

Built and used for a real personal recording pipeline. Config-driven throughout — nothing about
what you record is hard-coded into the tool; it only knows what you tell it in `config.json`.

## License

MIT — see [LICENSE](LICENSE). Use it, fork it, strip the DreDarkroom mark if you want; just don't
claim you wrote the original.

# Central CRM (mobile + Windows)

Open: https://offerpk.github.io/central-crm-mobile/

## Add Google Sheet (main goal)
1. Open the CRM link on phone or Windows.
2. Tap **+ Add Google Sheet**.
3. Share your Google Sheet as **Anyone with the link → Viewer**.
4. Paste the sheet link → **Fetch & save**.
5. Or upload a **CSV** if the sheet is private.

Data from added sheets is saved on that device (browser storage). Use **Export JSON** for backup.

## Multi-Drive storage (15TB + spillover)
Browser localStorage is only a cache. Durable CRM data is meant to live on Google Drive:

| Slot | Role | Default |
|------|------|---------|
| Drive 1 | Primary ~15TB | `user-Google-drive` connection |
| Drive 2 | Spillover | Attach when Drive 1 is full |
| Drive 3 | Spillover | Third account slot |

Registry file: `data/storage-drives.json` (also linked from Sources / Storage panel).

**How owner attaches Drive 2 tomorrow**
1. In Grok Bot, connect another Google Drive account (or ask CEO BOT).
2. Create / pick a folder on that Drive for Central CRM.
3. Run: `python3 scripts/drive_storage.py set-folder drive-2 FOLDER_ID user-Google-drive-2` (connection name as shown in Grok).
4. Then: `python3 scripts/drive_storage.py activate drive-2` (or `mark-full drive-1` to fail over automatically).
5. Check: `python3 scripts/drive_storage.py status`

UI: tap **Storage** next to Sources to see which drive is active and which slots are ready.

## Scrapers / multiple emails
Point each scraper at its own Google Sheet (public viewer link), then add those links in the CRM UI. Same CRM, many sources.

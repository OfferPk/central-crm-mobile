#!/usr/bin/env python3
"""Multi-Drive storage registry for Central CRM.

Manages data/storage-drives.json: active drive selection + spillover failover.
Does NOT call live Google Drive MCP — prints upload instructions only.

CLI:
  python3 drive_storage.py status
  python3 drive_storage.py activate drive-2
  python3 drive_storage.py mark-full drive-1
  python3 drive_storage.py set-folder drive-1 FOLDER_ID [connection]
  python3 drive_storage.py upload-instructions
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent  # site/
REGISTRY = ROOT / "data" / "storage-drives.json"
PKT = ZoneInfo("Asia/Karachi")


def now_pkt() -> str:
    return datetime.now(PKT).isoformat(timespec="seconds")


def load() -> dict:
    if not REGISTRY.exists():
        raise SystemExit(f"Registry missing: {REGISTRY}")
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def save(data: dict) -> None:
    data["updated_at"] = now_pkt()
    REGISTRY.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def by_id(data: dict, drive_id: str) -> dict | None:
    for d in data.get("drives") or []:
        if d.get("id") == drive_id:
            return d
    return None


ARMED_SPILLOVER_STATUSES = frozenset({
    "ready_spillover",
    "connected_arming",
    "active",
    "slot_ready",
})


def pick_write_drive(data: dict) -> dict | None:
    """Active drive if usable; else next armed spillover (prefer folder_id).

    Spillover arms when status is ready_spillover/connected_arming (or active)
    and a connection is set — even before Central CRM folder_id exists.
    """
    active_id = data.get("active_drive_id")
    active = by_id(data, active_id) if active_id else None
    if active and active.get("status") not in ("full",) and active.get("folder_id"):
        return active
    if active and active.get("status") == "active" and not active.get("folder_id"):
        # Primary selected but folder not yet attached — still report it,
        # then also surface next spillover candidate.
        pass
    # Failover: non-full candidates other than active (prefer folder_id, then armed)
    candidates = [
        d
        for d in (data.get("drives") or [])
        if d.get("status") != "full" and d.get("id") != (active or {}).get("id")
    ]
    with_folder = [d for d in candidates if d.get("folder_id")]
    if with_folder:
        return with_folder[0]
    armed = [
        d
        for d in candidates
        if d.get("status") in ARMED_SPILLOVER_STATUSES and d.get("connection")
    ]
    if armed:
        return armed[0]
    slot_ready = [d for d in candidates if d.get("status") == "slot_ready"]
    if slot_ready:
        return slot_ready[0]
    if active and active.get("status") != "full":
        return active
    return None


def _is_armed_spillover(d: dict) -> bool:
    return (
        d.get("role") == "spillover"
        and d.get("status") in ARMED_SPILLOVER_STATUSES
        and bool(d.get("connection"))
    )


def cmd_status(_: argparse.Namespace) -> int:
    data = load()
    active = by_id(data, data.get("active_drive_id", ""))
    write = pick_write_drive(data)
    print(f"Registry: {REGISTRY}")
    print(f"Updated:  {data.get('updated_at')}")
    print(f"Failover: {data.get('failover')} | auto_failover={data.get('auto_failover')}")
    print(f"Active:   {data.get('active_drive_id')}")
    if active:
        print(
            f"  → {active.get('label')} | status={active.get('status')} | "
            f"cap={active.get('capacity_tb')}TB | folder_id={active.get('folder_id') or '(empty)'} | "
            f"conn={active.get('connection') or '(none)'}"
        )
    print(f"Write pick: {(write or {}).get('id', '(none)')}")
    if write and write.get("id") != data.get("active_drive_id"):
        reason = []
        if active and active.get("status") == "full":
            reason.append("primary full")
        if active and not active.get("folder_id"):
            reason.append("primary missing folder_id")
        print(f"  (failover: {', '.join(reason) or 'spillover'})")
    armed = [d for d in (data.get("drives") or []) if _is_armed_spillover(d)]
    if armed:
        print("\nArmed spillover (writes land here if drive-1 full/write fails):")
        for d in armed:
            folder = d.get("folder_id") or "(folder tree pending)"
            print(
                f"  → {d.get('id')} {d.get('label')} | status={d.get('status')} | "
                f"conn={d.get('connection')} | owner={d.get('owner_email') or '—'} | "
                f"folder={folder}"
            )
    print("\nDrives:")
    for d in data.get("drives") or []:
        cap = d.get("capacity_tb")
        cap_s = f"{cap}TB" if cap is not None else "—"
        marker = "*" if d.get("id") == data.get("active_drive_id") else " "
        armed_tag = " ARMED" if _is_armed_spillover(d) else ""
        print(
            f" {marker} {d.get('id'):8} {d.get('label'):22} "
            f"status={str(d.get('status')):16} role={str(d.get('role')):9} "
            f"cap={cap_s:5} folder={d.get('folder_id') or '—'}{armed_tag}"
        )
    print("\nWrite targets:")
    for t in data.get("write_targets") or []:
        print(f"  - {t}")
    print(f"\nHow to attach next:\n  {data.get('how_to_attach_next')}")
    return 0


def cmd_activate(args: argparse.Namespace) -> int:
    data = load()
    d = by_id(data, args.drive_id)
    if not d:
        raise SystemExit(f"Unknown drive id: {args.drive_id}")
    for other in data.get("drives") or []:
        if other.get("id") == args.drive_id:
            other["status"] = "active"
        elif other.get("status") == "active":
            # demote previous primary/active to full or keep role-based
            if other.get("role") == "primary":
                other["status"] = "full" if other.get("status") == "full" else "slot_ready"
            elif other.get("status") == "active":
                other["status"] = "slot_ready"
    d["status"] = "active"
    data["active_drive_id"] = args.drive_id
    save(data)
    print(f"Activated {args.drive_id} ({d.get('label')}). active_drive_id updated.")
    if not d.get("folder_id"):
        print("NOTE: folder_id is empty — set it before uploading:")
        print(f"  python3 {Path(__file__).name} set-folder {args.drive_id} FOLDER_ID [connection]")
    return 0


def cmd_mark_full(args: argparse.Namespace) -> int:
    data = load()
    d = by_id(data, args.drive_id)
    if not d:
        raise SystemExit(f"Unknown drive id: {args.drive_id}")
    d["status"] = "full"
    # If this was active, flip to next spillover slot
    if data.get("active_drive_id") == args.drive_id:
        nxt = None
        for cand in data.get("drives") or []:
            if cand.get("id") == args.drive_id:
                continue
            if (
                cand.get("status") in ("slot_ready", "active", "ready_spillover", "connected_arming")
                or cand.get("folder_id")
                or (cand.get("role") == "spillover" and cand.get("connection"))
            ):
                nxt = cand
                break
        if nxt:
            nxt["status"] = "active"
            data["active_drive_id"] = nxt["id"]
            print(f"Failover → {nxt['id']} ({nxt.get('label')})")
        else:
            print("WARNING: no spillover slot available")
    save(data)
    print(f"Marked {args.drive_id} as full.")
    return 0


def cmd_set_folder(args: argparse.Namespace) -> int:
    data = load()
    d = by_id(data, args.drive_id)
    if not d:
        raise SystemExit(f"Unknown drive id: {args.drive_id}")
    d["folder_id"] = args.folder_id
    d["folder_url"] = f"https://drive.google.com/drive/folders/{args.folder_id}"
    if args.connection:
        d["connection"] = args.connection
    if d.get("status") == "slot_ready" and data.get("active_drive_id") == args.drive_id:
        d["status"] = "active"
    save(data)
    print(f"Set {args.drive_id} folder_id={args.folder_id} connection={d.get('connection') or '(unchanged)'}")
    return 0


def cmd_upload_instructions(_: argparse.Namespace) -> int:
    data = load()
    write = pick_write_drive(data)
    print("=== Central CRM Drive upload instructions ===")
    print("(No live MCP — use Grok Bot / CEO BOT Google Drive connector)\n")
    if not write:
        print("No writable drive selected. Attach a folder_id first.")
        return 1
    print(f"Target drive: {write.get('id')} — {write.get('label')}")
    print(f"  status:     {write.get('status')}")
    print(f"  connection: {write.get('connection') or '(set via Grok Bot Drive connector)'}")
    print(f"  folder_id:  {write.get('folder_id') or '(EMPTY — create folder then set-folder)'}")
    print(f"  folder_url: {write.get('folder_url') or '—'}")
    print("\nUpload these paths into the Drive folder:")
    for t in data.get("write_targets") or []:
        print(f"  • {t}")
    print("\nLocal mirrors on GitHub Pages site:")
    print("  site/data/leads.json")
    print("  site/data/sources.json")
    print("  site/data/central-crm.json")
    print(f"\n{data.get('how_to_attach_next')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Central CRM multi-Drive storage registry")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="Show registry + active / write pick")
    s.set_defaults(func=cmd_status)

    a = sub.add_parser("activate", help="Set active_drive_id and status=active")
    a.add_argument("drive_id")
    a.set_defaults(func=cmd_activate)

    m = sub.add_parser("mark-full", help="Mark drive full and fail over if it was active")
    m.add_argument("drive_id")
    m.set_defaults(func=cmd_mark_full)

    f = sub.add_parser("set-folder", help="Attach folder_id (+ optional connection) to a slot")
    f.add_argument("drive_id")
    f.add_argument("folder_id")
    f.add_argument("connection", nargs="?", default="")
    f.set_defaults(func=cmd_set_folder)

    u = sub.add_parser("upload-instructions", help="Print upload paths for active/write drive")
    u.set_defaults(func=cmd_upload_instructions)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

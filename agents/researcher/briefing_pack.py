from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def cycle_id_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def stable_hash(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def pack_to_markdown(pack: dict[str, Any]) -> str:
    freshness = pack.get("freshness", {}) if isinstance(pack.get("freshness", {}), dict) else {}
    sections = pack.get("sections", {}) if isinstance(pack.get("sections", {}), dict) else {}
    evidence = pack.get("evidence_ledger", []) if isinstance(pack.get("evidence_ledger", []), list) else []

    lines: list[str] = []
    lines.append("# BRIEFING PACK")
    lines.append("")
    lines.append(f"- cycle_id: {pack.get('cycle_id')}")
    lines.append(f"- generated_at: {pack.get('generated_at')}")
    lines.append(f"- contract_hash: {pack.get('contract_hash')}")
    lines.append(f"- authoritative_fresh: {freshness.get('authoritative_fresh')}")
    lines.append(f"- stale_mode_active: {freshness.get('stale_mode_active')}")
    lines.append("")

    lines.append("## Structural Context")
    lines.append(str(sections.get("structural_context", "")))
    lines.append("")

    lines.append("## Current Picture")
    lines.append(str(sections.get("current_picture", "")))
    lines.append("")

    lines.append("## Latest Stream Deltas")
    deltas = sections.get("latest_stream_deltas", [])
    if isinstance(deltas, list) and deltas:
        for item in deltas:
            if isinstance(item, dict):
                lines.append(
                    f"- [{item.get('timestamp', '')}] [{str(item.get('significance', '')).upper()}] "
                    f"{item.get('platform', '')}/{item.get('outlet', '')}: {item.get('headline', '')}"
                )
            else:
                lines.append(f"- {item}")
    else:
        lines.append("(none)")
    lines.append("")

    lines.append("## Relevant Prior Posts")
    prior_posts = sections.get("relevant_prior_posts", [])
    if isinstance(prior_posts, list) and prior_posts:
        for item in prior_posts:
            if isinstance(item, dict):
                lines.append(f"- {str(item.get('timestamp', ''))[:10]} | {item.get('title', '')}")
            else:
                lines.append(f"- {item}")
    else:
        lines.append("(none)")
    lines.append("")

    lines.append("## Working Theories")
    lines.append(str(sections.get("working_theories", "")))
    lines.append("")

    lines.append("## Evidence Ledger")
    if evidence:
        for item in evidence:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- [{item.get('id')}] ({item.get('authority')}) {item.get('kind')} | "
                f"{item.get('summary')} | {item.get('timestamp')} | {item.get('source_ref')}"
            )
    else:
        lines.append("(none)")

    return "\n".join(lines).strip() + "\n"


class BriefingPackManager:
    def __init__(self, root: str | Path, retention_count: int = 120):
        self.root = Path(root)
        self.cycles_dir = self.root / "cycles"
        self.latest_json = self.root / "latest.json"
        self.latest_md = self.root / "latest.md"
        self.retention_count = max(10, int(retention_count))
        self.root.mkdir(parents=True, exist_ok=True)
        self.cycles_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _atomic_write_text(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)

    @staticmethod
    def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        BriefingPackManager._atomic_write_text(path, text)

    def load_latest_json(self) -> dict[str, Any] | None:
        if not self.latest_json.exists():
            return None
        try:
            data = json.loads(self.latest_json.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def load_latest_markdown(self) -> str | None:
        if not self.latest_md.exists():
            return None
        try:
            return self.latest_md.read_text(encoding="utf-8")
        except Exception:
            return None

    def load_cycle(self, cycle_id: str) -> dict[str, Any] | None:
        target = self.cycles_dir / cycle_id / "pack.json"
        if not target.exists():
            return None
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def write_pack(self, pack: dict[str, Any], markdown: str) -> None:
        cycle_id = str(pack.get("cycle_id") or cycle_id_now())
        cycle_dir = self.cycles_dir / cycle_id
        cycle_dir.mkdir(parents=True, exist_ok=True)

        self._atomic_write_json(cycle_dir / "pack.json", pack)
        self._atomic_write_text(cycle_dir / "pack.md", markdown)

        self._atomic_write_json(self.latest_json, pack)
        self._atomic_write_text(self.latest_md, markdown)

        self.prune_retention()

    def prune_retention(self) -> None:
        cycle_dirs = sorted([p for p in self.cycles_dir.iterdir() if p.is_dir()], key=lambda p: p.name)
        if len(cycle_dirs) <= self.retention_count:
            return
        to_delete = cycle_dirs[: len(cycle_dirs) - self.retention_count]
        for directory in to_delete:
            for child in sorted(directory.rglob("*"), key=lambda p: len(p.parts), reverse=True):
                if child.is_file() or child.is_symlink():
                    child.unlink(missing_ok=True)
                elif child.is_dir():
                    try:
                        child.rmdir()
                    except OSError:
                        pass
            try:
                directory.rmdir()
            except OSError:
                pass


def pack_age_seconds(pack: dict[str, Any] | None) -> int | None:
    if not pack:
        return None
    generated_at = pack.get("generated_at")
    if not generated_at:
        return None
    try:
        dt = datetime.fromisoformat(str(generated_at).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds()))
    except Exception:
        return None

from __future__ import annotations

from pathlib import Path
import datetime as dt
import json
import shutil
import sqlite3

from .audio import (
    DEFAULT_LABELS,
    build_removed_path,
    format_duration,
    normalize_labels,
    scan_audio_files,
    unique_destination,
)
from .db import AuditStore
from .visualization import render_visualization


VALID_ACTIONS = {"approve", "remove", "skip"}
STATUS_BY_ACTION = {
    "approve": "approved",
    "remove": "removed",
    "skip": "skipped",
}


class AuditService:
    def __init__(self, db_path: Path) -> None:
        self.store = AuditStore(db_path)
        self.store.initialize()

    def load_root(self, root_path: str) -> dict:
        resolved_root = self._resolve_root_path(root_path)
        now = self._utc_now()
        scanned_items = scan_audio_files(resolved_root)

        with self.store.connect() as connection:
            root_row = self.store.get_or_create_root(connection, str(resolved_root), now)
            existing_by_relative = self.store.list_files_by_relative(connection, root_row["id"])
            seen_relative_paths: set[str] = set()

            for scanned_item in scanned_items:
                relative_path = scanned_item.relative_path.as_posix()
                seen_relative_paths.add(relative_path)
                existing = existing_by_relative.get(relative_path)

                payload = {
                    "root_id": root_row["id"],
                    "relative_path": relative_path,
                    "original_path": str(scanned_item.absolute_path),
                    "current_path": str(scanned_item.absolute_path),
                    "filename": scanned_item.absolute_path.name,
                    "extension": scanned_item.absolute_path.suffix.lower(),
                    "duration_seconds": scanned_item.duration_seconds,
                    "size_bytes": scanned_item.size_bytes,
                    "missing": 0,
                    "updated_at": now,
                }

                if existing is None:
                    payload.update(
                        {
                            "status": "pending",
                            "tags_json": "[]",
                            "note": "",
                            "last_action_at": None,
                            "created_at": now,
                        }
                    )
                    self.store.insert_file(connection, payload)
                    continue

                if existing["status"] == "removed":
                    removed_path = Path(existing["current_path"])
                    payload["current_path"] = str(removed_path)
                    payload["missing"] = 0 if removed_path.exists() else 1
                else:
                    payload["current_path"] = str(scanned_item.absolute_path)
                    payload["missing"] = 0

                self.store.update_file(connection, existing["id"], payload)

            for relative_path, existing in existing_by_relative.items():
                if relative_path in seen_relative_paths:
                    continue

                if existing["status"] == "removed":
                    current_path = Path(existing["current_path"])
                    missing = 0 if current_path.exists() else 1
                else:
                    current_path = Path(existing["original_path"])
                    missing = 0 if current_path.exists() else 1

                self.store.update_file(
                    connection,
                    existing["id"],
                    {
                        "current_path": str(current_path),
                        "missing": missing,
                        "updated_at": now,
                    },
                )

            root_row = self.store.get_root(connection, root_row["id"])
            return self._serialize_session(connection, root_row)

    def update_labels(self, root_id: int, labels: list[str]) -> dict:
        normalized_labels = normalize_labels(labels) or list(DEFAULT_LABELS)
        now = self._utc_now()

        with self.store.connect() as connection:
            root_row = self.store.get_root(connection, root_id)
            if root_row is None:
                raise ValueError(f"Unknown root id: {root_id}")

            updated_root = self.store.update_root_labels(
                connection,
                root_id,
                json.dumps(normalized_labels, ensure_ascii=False),
                now,
            )
            return {
                "root_id": root_id,
                "labels": self._deserialize_labels(updated_root["labels_json"]),
            }

    def apply_action(
        self,
        file_id: int,
        *,
        action: str,
        tags: list[str] | None = None,
        note: str = "",
    ) -> dict:
        if action not in VALID_ACTIONS:
            raise ValueError(f"Unsupported action: {action}")

        normalized_tags = normalize_labels(tags or [], limit=16)
        normalized_note = note.strip()
        now = self._utc_now()

        with self.store.connect() as connection:
            file_row = self.store.get_file(connection, file_id)
            if file_row is None:
                raise ValueError(f"Unknown file id: {file_id}")

            root_row = self.store.get_root(connection, file_row["root_id"])
            if root_row is None:
                raise ValueError(f"Unknown root id: {file_row['root_id']}")

            previous_state = self._row_state(file_row)
            next_status = STATUS_BY_ACTION[action]
            updates = {
                "status": next_status,
                "tags_json": json.dumps(normalized_tags, ensure_ascii=False),
                "note": normalized_note,
                "updated_at": now,
                "last_action_at": now,
            }

            current_path = Path(file_row["current_path"])
            original_path = Path(file_row["original_path"])

            if action == "remove":
                if file_row["status"] == "removed":
                    updates["current_path"] = str(current_path)
                    updates["missing"] = 0 if current_path.exists() else 1
                elif current_path.exists():
                    destination = unique_destination(
                        build_removed_path(Path(root_row["root_path"]), Path(file_row["relative_path"]))
                    )
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(current_path), str(destination))
                    updates["current_path"] = str(destination)
                    updates["missing"] = 0
                else:
                    updates["current_path"] = str(current_path)
                    updates["missing"] = 1
            else:
                if file_row["status"] == "removed" and current_path.exists():
                    original_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(current_path), str(original_path))
                    updates["current_path"] = str(original_path)
                    updates["missing"] = 0
                else:
                    updates["current_path"] = str(original_path)
                    updates["missing"] = 0 if original_path.exists() else 1

            updated_row = self.store.update_file(connection, file_id, updates)
            self.store.insert_event(
                connection,
                root_id=file_row["root_id"],
                file_id=file_id,
                action=action,
                previous_state_json=json.dumps(previous_state, ensure_ascii=False),
                new_state_json=json.dumps(self._row_state(updated_row), ensure_ascii=False),
                created_at=now,
            )

            return {
                "item": self._serialize_item(updated_row),
                "stats": self.store.get_stats(connection, file_row["root_id"]),
            }

    def undo_last(self, root_id: int) -> dict:
        with self.store.connect() as connection:
            root_row = self.store.get_root(connection, root_id)
            if root_row is None:
                raise ValueError(f"Unknown root id: {root_id}")

            event_row = self.store.get_last_event(connection, root_id)
            if event_row is None:
                raise LookupError("No action to undo")

            file_row = self.store.get_file(connection, event_row["file_id"])
            if file_row is None:
                raise ValueError(f"Unknown file id: {event_row['file_id']}")

            previous_state = json.loads(event_row["previous_state_json"])
            current_path = Path(file_row["current_path"])
            previous_path = Path(previous_state["current_path"])

            if current_path != previous_path and current_path.exists():
                previous_path.parent.mkdir(parents=True, exist_ok=True)
                if previous_path.exists():
                    raise RuntimeError(
                        f"Undo destination already exists: {previous_path}"
                    )
                shutil.move(str(current_path), str(previous_path))

            restored_row = self.store.update_file(
                connection,
                file_row["id"],
                {
                    "status": previous_state["status"],
                    "tags_json": json.dumps(previous_state["tags"], ensure_ascii=False),
                    "note": previous_state["note"],
                    "current_path": previous_state["current_path"],
                    "missing": int(previous_state["missing"]),
                    "last_action_at": previous_state["last_action_at"],
                    "updated_at": self._utc_now(),
                },
            )
            self.store.delete_event(connection, event_row["id"])

            return {
                "item": self._serialize_item(restored_row),
                "stats": self.store.get_stats(connection, root_id),
            }

    def export_root(self, root_id: int) -> tuple[str, bytes]:
        with self.store.connect() as connection:
            root_row = self.store.get_root(connection, root_id)
            if root_row is None:
                raise ValueError(f"Unknown root id: {root_id}")

            payload = self._serialize_session(connection, root_row)
            filename = f"audit-export-{root_id}.json"
            return filename, json.dumps(payload, ensure_ascii=False, indent=2).encode(
                "utf-8"
            )

    def get_audio_path(self, file_id: int) -> Path:
        with self.store.connect() as connection:
            file_row = self.store.get_file(connection, file_id)
            if file_row is None:
                raise ValueError(f"Unknown file id: {file_id}")

            path = Path(file_row["current_path"])
            if not path.exists():
                raise FileNotFoundError(path)
            return path

    def get_visualization(
        self,
        file_id: int,
        *,
        kind: str,
        width: int,
        height: int,
    ) -> bytes:
        audio_path = self.get_audio_path(file_id)
        return render_visualization(
            audio_path,
            kind=kind,
            width=width,
            height=height,
        )

    def _serialize_session(
        self, connection: sqlite3.Connection, root_row: sqlite3.Row
    ) -> dict:
        items = [self._serialize_item(row) for row in self.store.list_files(connection, root_row["id"])]
        stats = self.store.get_stats(connection, root_row["id"])
        selected_file_id = self._pick_selected_file_id(items)
        labels = self._deserialize_labels(root_row["labels_json"])

        return {
            "root": {
                "id": root_row["id"],
                "path": root_row["root_path"],
                "removed_dir": str(Path(root_row["root_path"]) / "_audit_removed"),
                "labels": labels,
                "updated_at": root_row["updated_at"],
            },
            "stats": stats,
            "selected_file_id": selected_file_id,
            "items": items,
        }

    def _serialize_item(self, row: sqlite3.Row) -> dict:
        duration_seconds = row["duration_seconds"]
        return {
            "id": row["id"],
            "root_id": row["root_id"],
            "relative_path": row["relative_path"],
            "filename": row["filename"],
            "original_path": row["original_path"],
            "current_path": row["current_path"],
            "status": row["status"],
            "tags": self._deserialize_tags(row["tags_json"]),
            "note": row["note"] or "",
            "missing": bool(row["missing"]),
            "duration_seconds": duration_seconds,
            "duration_label": format_duration(duration_seconds),
            "size_bytes": row["size_bytes"],
            "last_action_at": row["last_action_at"],
            "audio_url": f"/api/files/{row['id']}/audio",
            "visualization_base_url": f"/api/files/{row['id']}/visualization",
        }

    def _row_state(self, row: sqlite3.Row) -> dict:
        return {
            "status": row["status"],
            "tags": self._deserialize_tags(row["tags_json"]),
            "note": row["note"] or "",
            "current_path": row["current_path"],
            "missing": bool(row["missing"]),
            "last_action_at": row["last_action_at"],
        }

    def _pick_selected_file_id(self, items: list[dict]) -> int | None:
        for status in ("pending", "skipped"):
            for item in items:
                if item["status"] == status and not item["missing"]:
                    return item["id"]
        for item in items:
            if not item["missing"]:
                return item["id"]
        return items[0]["id"] if items else None

    def _resolve_root_path(self, root_path: str) -> Path:
        resolved = Path(root_path).expanduser().resolve()
        if not resolved.exists() or not resolved.is_dir():
            raise ValueError(f"Directory does not exist: {resolved}")
        return resolved

    def _deserialize_tags(self, raw_value: str | None) -> list[str]:
        if not raw_value:
            return []
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, list):
            return []
        return [str(value) for value in parsed]

    def _deserialize_labels(self, raw_value: str | None) -> list[str]:
        labels = self._deserialize_tags(raw_value)
        return labels or list(DEFAULT_LABELS)

    def _utc_now(self) -> str:
        return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        )

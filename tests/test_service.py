from __future__ import annotations

from pathlib import Path
import wave

from audio_audit.service import AuditService


def write_test_wave(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16_000)
        wav_file.writeframes(b"\x00\x00" * 16_000)


def test_remove_and_undo(tmp_path: Path) -> None:
    root_path = tmp_path / "dataset"
    audio_path = root_path / "speaker_a" / "clip.wav"
    write_test_wave(audio_path)

    service = AuditService(tmp_path / "audit.db")
    session = service.load_root(str(root_path))

    assert session["stats"]["total"] == 1
    assert session["stats"]["pending"] == 1
    assert session["items"][0]["status"] == "pending"

    file_id = session["items"][0]["id"]
    root_id = session["root"]["id"]
    remove_result = service.apply_action(
        file_id,
        action="remove",
        tags=["噪声"],
        note="存在明显底噪",
    )

    removed_item = remove_result["item"]
    assert removed_item["status"] == "removed"
    assert removed_item["tags"] == ["噪声"]
    assert not audio_path.exists()
    assert (root_path / "_audit_removed" / "speaker_a" / "clip.wav").exists()

    undo_result = service.undo_last(root_id)
    restored_item = undo_result["item"]
    assert restored_item["status"] == "pending"
    assert audio_path.exists()
    assert not (root_path / "_audit_removed" / "speaker_a" / "clip.wav").exists()

"""설정 쓰기. UI 가 손대는 파일은 self.md 와 hikidev.yaml 둘뿐.

hikidev.yaml 은 주석이 설계의 일부라 yaml.dump 로 다시 쓰지 않는다. 섹션 안의 `key: value` 줄을 찾아 값만 바꾼다.
self.md 는 hikidev 의 것이라 주인이 손댔다는 사실을 `.hikidev/ui-changes.jsonl` 에 한 줄 남긴다 (journal 은 걔 것).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from hikidev.home import HikidevHome, now_iso


@dataclass(frozen=True, slots=True)
class Field:
    section: str
    key: str
    label: str
    kind: str
    """int | float | str | choice"""
    help: str = ""
    choices: tuple[str, ...] = ()


FIELDS: tuple[Field, ...] = (
    Field("schedule", "heartbeat_minutes", "심장박동 주기 (분)", "int", "이 간격으로 깨운다"),
    Field("schedule", "max_active_hours_per_day", "하루 가동 상한 (시간)", "float", "넘으면 자정까지 잔다"),
    Field("schedule", "rate_limit_fallback_minutes", "rate limit 대기 (분)", "int", "리셋 시각을 모를 때"),
    Field("session", "context_window_tokens", "컨텍스트 창 (토큰)", "int"),
    Field("session", "context_soft", "새 채팅 권유 임계치", "float", "0~1. 넘으면 신호에 한 줄, 결정은 hikidev"),
    Field("session", "context_threshold", "강제 새 채팅 임계치", "float", "0~1. 넘으면 인수인계 후 새 채팅"),
    Field("session", "max_turns", "세션당 최대 턴", "int"),
    Field("session", "timeout_minutes", "세션 타임아웃 (분)", "int"),
    Field(
        "session",
        "permission_mode",
        "권한 모드",
        "choice",
        "자기 방 안이니까 bypass 가 기본",
        ("bypassPermissions", "acceptEdits", "default", "plan"),
    ),
    Field("session", "max_consecutive_failures", "연속 실패 허용", "int", "같은 세션에서 이 횟수면 새 채팅"),
    Field("discord", "channel_id", "디스코드 채널 ID", "str"),
    Field("discord", "owner_id", "주인 디스코드 ID", "str", "승인 버튼을 누를 수 있는 사람"),
    Field("discord", "approval_timeout_hours", "승인 대기 (시간)", "float"),
)


def current_values(yaml_path: Path) -> dict[str, Any]:
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) if yaml_path.exists() else {}
    data = data or {}
    out = {}
    for f in FIELDS:
        v = (data.get(f.section) or {}).get(f.key)
        out[f"{f.section}.{f.key}"] = "" if v is None else v
    return out


def coerce(f: Field, raw: str) -> Any:
    raw = raw.strip()
    if f.kind == "int":
        v = int(raw)
        if v < 0:
            raise ValueError("음수")
        return v
    if f.kind == "float":
        fv = float(raw)
        if fv < 0:
            raise ValueError("음수")
        return int(fv) if fv.is_integer() else fv
    if f.kind == "choice":
        if raw not in f.choices:
            raise ValueError(f"허용값: {', '.join(f.choices)}")
        return raw
    return raw


def _same(a: Any, b: Any) -> bool:
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return str(a) == str(b)


def _yaml_scalar(f: Field, v: Any) -> str:
    if f.kind in ("int", "float"):
        return repr(v)
    s = str(v)
    # 채널 ID 같은 긴 숫자 문자열은 따옴표로 (yaml 이 int 로 읽지 않게)
    if f.kind == "str" and (re.fullmatch(r"\d+", s) or not s or ":" in s or "#" in s):
        return json.dumps(s, ensure_ascii=False)
    return s


def replace_values(text: str, changes: dict[tuple[str, str], Any]) -> str:
    """섹션 아래 `  key: value   # 주석` 줄의 value 만 바꾼다. 섹션이나 키가 없으면 섹션 끝에 추가."""
    lines = text.splitlines()
    by_section: dict[str, dict[str, Any]] = {}
    for (sec, key), v in changes.items():
        by_section.setdefault(sec, {})[key] = v

    field_of = {(f.section, f.key): f for f in FIELDS}

    for sec, kv in by_section.items():
        # 섹션 범위 찾기
        start = next((i for i, ln in enumerate(lines) if re.match(rf"^{re.escape(sec)}\s*:\s*(#.*)?$", ln)), None)
        if start is None:
            lines += ["", f"{sec}:"]
            start = len(lines) - 1
        end = start + 1
        while end < len(lines) and (
            not lines[end].strip() or lines[end].startswith((" ", "\t")) or lines[end].startswith("#")
        ):
            end += 1
        # 뒤쪽 빈 줄은 섹션에 안 넣는다
        while end > start + 1 and not lines[end - 1].strip():
            end -= 1

        for key, v in kv.items():
            f = field_of[(sec, key)]
            scalar = _yaml_scalar(f, v)
            pat = re.compile(rf"^(\s+{re.escape(key)}\s*:\s*)([^#\n]*?)(\s*#.*)?$")
            for i in range(start + 1, end):
                m = pat.match(lines[i])
                if m:
                    lines[i] = f"{m.group(1)}{scalar}{m.group(3) or ''}"
                    break
            else:
                lines.insert(end, f"  {key}: {scalar}")
                end += 1
    return "\n".join(lines) + ("\n" if text.endswith("\n") or not text else "")


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def log_change(home: HikidevHome, file: str, note: str) -> None:
    home.dot.mkdir(parents=True, exist_ok=True)
    with (home.dot / "ui-changes.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": now_iso(), "by": "owner/ui", "file": file, "note": note}, ensure_ascii=False) + "\n")


def save_yaml(home: HikidevHome, form: dict[str, str]) -> tuple[list[str], list[str]]:
    """form 의 `section.key` 값 → hikidev.yaml. (바뀐 키 목록, 오류 목록)"""
    path = home.config_yaml
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    before = current_values(path)
    changes: dict[tuple[str, str], Any] = {}
    errors: list[str] = []
    for f in FIELDS:
        name = f"{f.section}.{f.key}"
        if name not in form:
            continue
        try:
            v = coerce(f, form[name])
        except ValueError as e:
            errors.append(f"{f.label}: {form[name]!r} ({e})")
            continue
        if not _same(before.get(name), v):
            changes[(f.section, f.key)] = v
    if errors or not changes:
        return [], errors
    new_text = replace_values(text, changes)
    try:
        parsed = yaml.safe_load(new_text) or {}
    except yaml.YAMLError as e:
        return [], [f"yaml 이 깨져서 저장하지 않았다: {e}"]
    for (sec, key), v in changes.items():
        got = (parsed.get(sec) or {}).get(key)
        if not _same(got, v):
            return [], [f"{sec}.{key} 가 {v!r} 로 안 바뀌었다 ({got!r}). 저장하지 않았다."]
    _atomic_write(path, new_text)
    changed = [f"{s}.{k}" for s, k in changes]
    log_change(home, "hikidev.yaml", ", ".join(f"{s}.{k}={changes[(s, k)]}" for s, k in changes))
    return changed, []


def save_self(home: HikidevHome, text: str) -> bool:
    """self.md 저장. 바뀐 게 없으면 False."""
    text = text.replace("\r\n", "\n")
    if not text.endswith("\n"):
        text += "\n"
    old = home.self_md.read_text(encoding="utf-8") if home.self_md.exists() else ""
    if old == text:
        return False
    _atomic_write(home.self_md, text)
    log_change(home, "self.md", f"주인이 UI 에서 고침 ({len(old)} → {len(text)} 글자)")
    return True

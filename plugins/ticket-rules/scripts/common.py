"""규칙 스크립트가 함께 쓰는 입출력, 레포 찾기, 세션당 한 번 처리, 발동 기록."""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# 발동 기록은 레포가 아니라 사용자 폴더 한 곳에 모은다. 테스트는 환경 변수로 위치를 바꾼다.
LOG = Path(os.environ.get("TICKET_RULES_LOG") or Path.home() / ".claude" / "ticket-rules" / "fired.log")
STATE_DIR = Path(tempfile.gettempdir()) / "ticket-rules"


def read_event() -> dict:
    return json.loads(sys.stdin.buffer.read() or b"{}")


def git_dir(root: Path) -> Path | None:
    dot = root / ".git"
    if dot.is_file():  # worktree는 .git이 "gitdir: <경로>" 파일이다
        text = dot.read_text(encoding="utf-8", errors="ignore").strip()
        return Path(text[len("gitdir:"):].strip()) if text.startswith("gitdir:") else None
    return dot if (dot / "HEAD").exists() else None  # 빈 .git 폴더는 레포가 아니다


def is_team_repo(root: Path) -> bool:
    """ticket-project 조직 레포만 대상이다. 플러그인은 다른 프로젝트 세션에서도 돌기 때문에 여기서 거른다."""
    gitdir = git_dir(root)
    if gitdir is None:
        return False
    common = gitdir / "commondir"  # worktree의 설정은 원본 레포 쪽에 있다
    if common.exists():
        gitdir = (gitdir / common.read_text(encoding="utf-8").strip()).resolve()
    config = gitdir / "config"
    text = config.read_text(encoding="utf-8", errors="ignore") if config.exists() else ""
    return "github.com/ticket-project/" in text or "github.com:ticket-project/" in text


def repo_root(path: Path) -> Path | None:
    # 플러그인은 어느 폴더에서 연 세션에서도 돌므로, 스크립트 위치가 아니라 대상 경로로 레포를 찾는다.
    for candidate in [path, *path.parents]:
        if git_dir(candidate):
            return candidate
    return None


def team_root(path: Path) -> Path | None:
    root = repo_root(path)
    return root if root and is_team_repo(root) else None


def session_cwd(event: dict) -> Path:
    return Path(event.get("cwd") or ".").resolve()


def session_repos(event: dict) -> list[Path]:
    """세션이 연 팀 레포. 워크스페이스 루트처럼 레포가 아닌 폴더면 바로 아래 팀 레포들."""
    cwd = session_cwd(event)
    root = repo_root(cwd)
    if root:
        return [root] if is_team_repo(root) else []
    return [child for child in sorted(cwd.iterdir()) if child.is_dir() and git_dir(child) and is_team_repo(child)]


def written_file(event: dict) -> tuple[Path, str] | None:
    raw = (event.get("tool_input") or {}).get("file_path")
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = session_cwd(event) / path
    path = path.resolve()
    root = team_root(path.parent)
    return (root, path.relative_to(root).as_posix()) if root else None


def git(root: Path, *args: str) -> list[str] | None:
    out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8")
    return [line for line in out.stdout.splitlines() if line] if out.returncode == 0 else None


def first_time(event: dict, point: str, rule: str) -> bool:
    """같은 규칙은 지점마다 세션당 한 번. Stop을 다시 막는 무한 반복도 여기서 끊긴다."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    marker = STATE_DIR / f"{event.get('session_id', 'unknown')}.{point}.{rule}"
    if marker.exists():
        return False
    marker.touch()
    return True


def record(event: dict, point: str, rule: str, repo: Path, hits: list[str]) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "session": event.get("session_id"), "repo": repo.name,
             "point": point, "rule": rule, "hits": hits}
    with LOG.open("a", encoding="utf-8") as log:
        log.write(json.dumps(entry, ensure_ascii=False) + "\n")


def emit(point: str, text: str) -> None:
    if point == "Stop":
        out = {"decision": "block", "reason": text}
    else:
        out = {"hookSpecificOutput": {"hookEventName": point, "additionalContext": text}}
    print(json.dumps(out))

"""hook 스크립트를 실제처럼(JSON 입력 → 출력) 돌려 보는 자체 검사. 실행: python tests/test_rules.py"""

import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def run(script: str, event: dict, log: Path) -> dict | None:
    out = subprocess.run([sys.executable, str(SCRIPTS / script)], input=json.dumps(event).encode(),
                         capture_output=True, env={**os.environ, "TICKET_RULES_LOG": str(log)})
    assert out.returncode == 0, out.stderr.decode("utf-8")
    text = out.stdout.decode("utf-8").strip()
    return json.loads(text) if text else None


def write(root: Path, rel: str, body: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def ticket_repo(workspace: Path, name: str = "ticket", remote: str = "https://github.com/ticket-project/ticket-core.git") -> Path:
    root = workspace / name
    base = "src/main/java/com/ticket"
    write(root, f"{base}/like/package-info.java",
          '@org.springframework.modulith.ApplicationModule(allowedDependencies = {"member :: api", "shared :: exception"})\npackage com.ticket.like;\n')
    write(root, f"{base}/member/package-info.java", "@org.springframework.modulith.ApplicationModule\npackage com.ticket.member;\n")
    write(root, f"{base}/plain/Plain.java", "package com.ticket.plain;\n")
    write(root, "build.gradle", "")
    git(root, "init", "-q")
    git(root, "remote", "add", "origin", remote)
    git(root, "add", ".")
    git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    return root


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        log = workspace / "fired.log"
        (workspace / ".git").mkdir()  # 빈 .git 폴더는 레포로 보지 않는다
        root = ticket_repo(workspace)
        other = ticket_repo(workspace, "other", "https://github.com/someone/other.git")
        fe = workspace / "ticket-fe"
        write(fe, "package.json", json.dumps({"dependencies": {"next": "16"}}))
        git(fe, "init", "-q")
        git(fe, "remote", "add", "origin", "git@github.com:ticket-project/ticket-fe.git")

        def post(script: str, rel: str, body: str, session: str) -> dict | None:
            path = write(root, rel, body)
            return run(script, {"session_id": session, "hook_event_name": "PostToolUse", "cwd": str(root),
                                "tool_input": {"file_path": str(path)}}, log)

        usecase = "src/main/java/com/ticket/booking/order/usecase/Probe.java"
        redisson = "import com.ticket.booking.hold.persistence.RedissonHoldStore;\nclass Probe {}\n"

        # 작성 직후: persistence 구현 참조는 안내하고, 같은 세션에서는 다시 안내하지 않는다.
        s1 = uuid.uuid4().hex
        out = post("usecase_persistence.py", usecase, redisson, s1)
        assert "RedissonHoldStore" in out["hookSpecificOutput"]["additionalContext"], out
        assert post("usecase_persistence.py", usecase, redisson, s1) is None
        # QuerydslRepository는 예외다.
        assert post("usecase_persistence.py", usecase,
                    "import com.ticket.show.persistence.ShowQuerydslRepository;\n", uuid.uuid4().hex) is None

        # 끝내기 직전: 셸로 만든 위반(untracked)도 잡는다. 레포에서 연 세션과 워크스페이스 루트에서 연 세션 모두.
        write(root, usecase, redisson)
        for cwd in (root, workspace):
            s2 = uuid.uuid4().hex
            out = run("usecase_persistence.py", {"session_id": s2, "hook_event_name": "Stop", "cwd": str(cwd)}, log)
            assert out and out["decision"] == "block" and "Probe.java" in out["reason"], (cwd, out)
            assert run("usecase_persistence.py", {"session_id": s2, "hook_event_name": "Stop", "cwd": str(cwd)}, log) is None
        (root / usecase).unlink()

        # 모듈 경계: 허용된 api는 조용하고, 내부 참조는 허용 목록과 함께 안내한다.
        like = "src/main/java/com/ticket/like/usecase/LikeProbe.java"
        assert post("module_boundary.py", like, "import com.ticket.member.api.MemberLookupApi;\n", uuid.uuid4().hex) is None
        assert post("module_boundary.py", like, "/** {@code com.ticket.member.domain.Member} 설명 */\n", uuid.uuid4().hex) is None
        out = post("module_boundary.py", like, "import com.ticket.member.domain.Member;\n", uuid.uuid4().hex)
        text = out["hookSpecificOutput"]["additionalContext"]
        assert "com.ticket.member.domain.Member" in text and "member :: api" in text, text
        # @ApplicationModule이 없는 module은 판정하지 않는다.
        assert post("module_boundary.py", "src/main/java/com/ticket/plain/P.java",
                    "import com.ticket.member.domain.Member;\n", uuid.uuid4().hex) is None

        # ticket-project 조직이 아닌 레포는 레이아웃이 같아도 아무것도 하지 않는다.
        stranger = write(other, usecase, redisson)
        assert run("usecase_persistence.py", {"session_id": uuid.uuid4().hex, "hook_event_name": "PostToolUse",
                                              "cwd": str(other), "tool_input": {"file_path": str(stranger)}}, log) is None
        assert run("usecase_persistence.py", {"session_id": uuid.uuid4().hex, "hook_event_name": "Stop",
                                              "cwd": str(other)}, log) is None
        assert run("session_start.py", {"session_id": "s", "hook_event_name": "SessionStart", "cwd": str(other)}, log) is None
        stranger.unlink()

        # ticket-core 레이아웃이 아닌 레포는 규칙 대상이 아니다.
        page = write(fe, "src/usecase/x.java", redisson)
        assert run("usecase_persistence.py", {"session_id": uuid.uuid4().hex, "hook_event_name": "PostToolUse",
                                              "cwd": str(fe), "tool_input": {"file_path": str(page)}}, log) is None

        # 세션 시작 안내: 레포 종류에 맞는 안내만 넣는다.
        def start(cwd: Path) -> str:
            return run("session_start.py", {"session_id": "s", "hook_event_name": "SessionStart", "cwd": str(cwd)},
                       log)["hookSpecificOutput"]["additionalContext"]

        spring = start(root)
        assert "[Spring/Gradle 레포]" in spring and "[Next.js 레포]" not in spring and "ticket(브랜치" in spring, spring
        nxt = start(fe)
        assert "[Next.js 레포]" in nxt and "[Spring/Gradle 레포]" not in nxt, nxt
        top = start(workspace)
        assert "ticket(브랜치" in top and "ticket-fe(브랜치" in top and "로드되지 않는다" in top, top
        assert "other(" not in top, top

        records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        assert {r["point"] for r in records} == {"PostToolUse", "Stop"} and all(r["repo"] for r in records), records
    print("ok")


if __name__ == "__main__":
    main()

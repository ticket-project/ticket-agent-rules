"""세션 시작 때 팀 공통 안내와, 레포 종류에 맞는 안내만 에이전트 컨텍스트에 넣는다.

레포 종류는 표식 파일로 고른다(build.gradle → Spring/Gradle, package.json의 next → Next.js).
맞지 않는 안내는 넣지 않는다. 각 레포 규칙의 원본은 그 레포의 AGENTS.md이고, 여기에는 레포를 가리지 않는
팀 약속과 도구 사용법만 둔다.
"""

import json
from pathlib import Path

from common import emit, git, read_event, repo_root, session_cwd, session_repos

COMMON = """[팀 공통 안내] ticket-rules 플러그인이 세션 시작 때 넣는 안내다.
- 응답과 문서는 한국어로 쓴다. 각 레포의 AGENTS.md가 그 레포 규칙의 원본이다.
- 같은 체크아웃에서 다른 세션이 동시에 작업하고 커밋할 수 있다. 스테이징은 파일 경로를 하나씩 적고 `git add .`, `git add -A`, 디렉터리 단위 add는 쓰지 않는다."""

SPRING = """[Spring/Gradle 레포]
- Windows PowerShell에서는 `.\\gradlew.bat`, Git Bash에서는 `./gradlew`를 쓴다.
- 테스트는 바꾼 범위의 `--tests`부터 돌리고 필요할 때 넓힌다.
- 같은 체크아웃의 `build/`를 여러 세션이 함께 쓴다. Gradle을 동시에 돌리면 `build/test-results`가 지워지며 실패할 수 있으니, 실패하면 다른 실행이 끝난 뒤 다시 돌린다."""

NEXT = """[Next.js 레포]
- 패키지 매니저는 pnpm이다(`pnpm-lock.yaml`). npm·yarn으로 설치하지 않는다.
- 검사는 `pnpm lint`, 빌드 확인은 `pnpm build`다."""


def state(root: Path) -> str:
    lines = git(root, "status", "--porcelain=v1", "--branch") or []
    branch = lines[0][3:].split("...")[0] if lines and lines[0].startswith("## ") else "?"
    return f"{root.name}(브랜치 {branch}, 커밋 안 된 변경 {max(len(lines) - 1, 0)}개)"


def guides(root: Path) -> list[str]:
    found = []
    if any((root / name).exists() for name in ("build.gradle", "build.gradle.kts", "settings.gradle")):
        found.append(SPRING)
    package = root / "package.json"
    if package.exists() and "next" in json.loads(package.read_text(encoding="utf-8")).get("dependencies", {}):
        found.append(NEXT)
    return found


def main() -> None:
    event = read_event()
    repos = session_repos(event)
    if not repos:
        return  # ticket-project 레포가 아닌 세션에는 아무것도 넣지 않는다
    parts = [COMMON]
    if repo_root(session_cwd(event)):
        root = repos[0]
        parts[0] += f"\n- 지금 레포: {state(root)}. 커밋 안 된 변경은 다른 작업일 수 있으니 되돌리거나 내 커밋에 섞지 않는다."
        parts += guides(root)
    else:
        parts[0] += (
            "\n- 이 세션은 여러 레포를 담은 폴더에서 열렸다: " + ", ".join(state(r) for r in repos) + "."
            "\n- 이 위치에서는 각 레포의 `.claude/settings.json`(권한·hook)이 로드되지 않는다. "
            "한 레포만 오래 다루면 그 레포 폴더에서 세션을 여는 편이 낫다."
        )
    emit("SessionStart", "\n\n".join(parts))


if __name__ == "__main__":
    main()

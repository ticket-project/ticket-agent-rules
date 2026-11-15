"""usecase·event가 persistence 구현을 직접 참조하면 그 규칙을 에이전트 컨텍스트에 넣는다.

- PostToolUse(Write/Edit 직후): 방금 쓴 파일 하나만 본다. 그 자리에서 고치게 하는 용도다.
- Stop(끝내기 직전): 세션이 연 레포의 브랜치 변경 전체를 본다. 셸로 고쳐 PostToolUse를 건너뛴 파일까지 잡는 안전망이다.

정규식은 후보만 좁힌다. 고칠지는 규칙을 받은 에이전트가 판단한다. 규칙의 원본은
ticket-core의 ArchitectureRulesTest.usecase와_event는_저장_구현과_HTTP를_모른다 다.
"""

import re
from pathlib import Path

from common import emit, first_time, git, read_event, record, session_repos, written_file

RULE = "usecase-persistence-impl"
PERSISTENCE_REF = re.compile(r"\bcom\.ticket\.[\w.]*?\.persistence\.(\w+|\*)")
HEADERS = {
    "PostToolUse": "[ticket-core 팀 규칙] 방금 쓴 코드에 아래 규칙을 적용해 줘.",
    "Stop": "[ticket-core 팀 규칙] 끝내기 전에, 이번 변경이 아래 규칙에 닿는다. 한 번만 다시 확인해 줘. "
    "이미 지키고 있으면 그대로 두고 끝내라. 실패가 아니라 재확인이다.",
}
RULE_TEXT = """usecase·event는 저장 구현(persistence)을 직접 참조하지 않는다
{hits}
조립은 계약(domain *Repository, port의 output port)만 부르고 저장 구현 선택은 persistence가 갖는다. 구현이 필요하면 계약 뒤에 두고 use case는 계약 타입으로 받는다. 예외는 같은 module의 *QuerydslRepository 조회뿐이다.
(rule: usecase-persistence-impl)"""


def applies(root: Path) -> bool:
    return (root / "src" / "main" / "java" / "com" / "ticket").is_dir()  # ticket-core 단일 모듈 레이아웃


def changed_files(root: Path) -> list[str]:
    # 세션 중에 커밋해도 빠지지 않게 브랜치 분기점부터 본다. 새로 만든(untracked) 파일도 포함한다.
    diff = git(root, "diff", "--name-only", "--merge-base", "origin/master") or git(root, "diff", "--name-only", "HEAD") or []
    return sorted(set(diff) | set(git(root, "ls-files", "--others", "--exclude-standard") or []))


def hits(root: Path, rel: str) -> list[str]:
    path = root / rel
    if not (rel.startswith("src/main/java/") and rel.endswith(".java") and re.search(r"/(usecase|event)/", rel)):
        return []
    if not path.exists():
        return []
    names = sorted(set(PERSISTENCE_REF.findall(path.read_text(encoding="utf-8"))))
    # shortcut: 이름만 본다. ArchUnit은 JPAQueryFactory 보유까지 보니 애매하면 architectureTest가 최종 기준이다.
    return [f"- {rel} → persistence.{name}" for name in names if not name.endswith("QuerydslRepository")]


def main() -> None:
    event = read_event()
    point = event.get("hook_event_name", "Stop")
    if point == "PostToolUse":
        written = written_file(event)
        targets = [written] if written and applies(written[0]) else []
    else:
        targets = [(root, rel) for root in session_repos(event) if applies(root) for rel in changed_files(root)]
    found = [(root, hit) for root, rel in targets for hit in hits(root, rel)]
    if not found or not first_time(event, point, RULE):
        return
    lines = [hit for _, hit in found]
    record(event, point, RULE, found[0][0], lines)
    emit(point, HEADERS[point] + "\n\n" + RULE_TEXT.format(hits="\n".join(lines)))


if __name__ == "__main__":
    main()

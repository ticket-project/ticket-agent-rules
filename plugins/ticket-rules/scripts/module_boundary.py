"""방금 쓴 파일이 다른 module의 공개 계약 밖을 참조하면 그 규칙을 에이전트 컨텍스트에 넣는다.

PostToolUse(Write/Edit 직후)에서 방금 쓴 파일 하나만 본다. 허용 목록은 쓰는 쪽 module의
package-info.java `allowedDependencies`를 그대로 읽으므로 따로 관리할 목록이 없다. Spring Modulith
`@ApplicationModule`이 선언된 module에만 적용한다. 규칙의 원본은 ticket-core의 ModularityTests다.
"""

import re
from pathlib import Path

from common import emit, first_time, read_event, record, written_file

RULE = "module-boundary"
REF = re.compile(r"\bcom\.ticket\.([a-z]\w*)\.([\w.]*\w)")
ALLOWED = re.compile(r'"(\w+)\s*::\s*(\w+)"')
COMMENT = re.compile(r"/\*.*?\*/|//[^\n]*", re.S)
# named interface 이름 = 공개 package 이름. 예외: shared의 config는 package가 아니라 이 타입만 연다.
INTERFACE_PATH = {"config": "config.CorsProperties"}

RULE_TEXT = """[ticket-core 팀 규칙] 방금 쓴 코드에 아래 규칙을 적용해 줘.

module은 다른 module의 공개 계약만 참조한다
{hits}
다른 module은 쓰는 쪽 package-info.java의 allowedDependencies에 적힌 named interface로만 부른다. 다른 module의 domain·usecase·persistence·entity가 필요하면 그 module의 api에 계약을 추가하고, 새 의존 방향이 필요하면 allowedDependencies와 ModularityTests의 승인 DAG를 함께 검토한다.
{module}의 allowedDependencies: {allowed}
(rule: module-boundary)"""


def module_info(modules: Path, module: str) -> str | None:
    info = modules / module / "package-info.java"
    text = info.read_text(encoding="utf-8") if info.exists() else ""
    return text if "ApplicationModule" in text else None


def is_open(target: str, rest: str, allowed: list[tuple[str, str]]) -> bool:
    for module, interface in allowed:
        path = INTERFACE_PATH.get(interface, interface)
        if module == target and (rest == path or rest.startswith(path + ".")):
            return True
    return False


def check(root: Path, rel: str) -> tuple[str, list[tuple[str, str]], list[str]] | None:
    match = re.fullmatch(r"src/main/java/com/ticket/(\w+)/.+\.java", rel)
    if not match or not (root / rel).exists():
        return None
    modules = root / "src" / "main" / "java" / "com" / "ticket"
    module = match.group(1)
    info = module_info(modules, module)
    if info is None:
        return None  # Modulith module이 아니면 허용 목록이 없어 판정하지 않는다
    allowed = ALLOWED.findall(info)
    # javadoc이 다른 module 클래스를 설명용으로 언급하는 경우가 있어 주석은 지우고 본다.
    code = COMMENT.sub("", (root / rel).read_text(encoding="utf-8"))
    refs = sorted(
        {
            (target, rest)
            for target, rest in REF.findall(code)
            if target != module and (modules / target).is_dir() and not is_open(target, rest, allowed)
        }
    )
    hits = [f"- {rel} → com.ticket.{target}.{rest}" for target, rest in refs]
    return (module, allowed, hits) if hits else None


def main() -> None:
    event = read_event()
    written = written_file(event)
    found = check(*written) if written else None
    if not found or not first_time(event, "PostToolUse", RULE):
        return
    module, allowed, hits = found
    record(event, "PostToolUse", RULE, written[0], hits)
    emit("PostToolUse", RULE_TEXT.format(
        hits="\n".join(hits), module=module, allowed=", ".join(f"{m} :: {i}" for m, i in allowed) or "(없음)"))


if __name__ == "__main__":
    main()

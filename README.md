# ticket-agent-rules

ticket-project 레포에서 Claude Code 에이전트에게 팀 규칙을 **필요한 순간에만** 다시 알려 주는 플러그인 마켓플레이스다. 규칙을 레포마다 복사하지 않고 여기 한 곳에서 고치면, 자동 업데이트를 켠 사람은 다음 세션부터 새 규칙을 받는다.

## 들어 있는 것

플러그인 `ticket-rules` 하나에 아래가 들어 있다. ticket-project 조직 레포(`github.com/ticket-project/...`)에서만 동작하고, 다른 프로젝트 세션에는 아무것도 넣지 않는다.

| 시점 | 스크립트 | 하는 일 |
| --- | --- | --- |
| 세션 시작 | `session_start.py` | 팀 공통 안내, 지금 레포의 브랜치·미커밋 변경 수, 레포 종류에 맞는 안내(Spring/Gradle, Next.js) |
| 파일 작성 직후 | `usecase_persistence.py` | ticket-core에서 usecase·event가 persistence 구현을 직접 참조하면 규칙 안내 |
| 파일 작성 직후 | `module_boundary.py` | ticket-core에서 다른 module의 공개 계약 밖을 참조하면 규칙 안내(허용 목록은 `package-info.java`의 `allowedDependencies`) |
| 끝내기 직전 | `usecase_persistence.py` | 브랜치 변경 전체를 다시 보고 한 번 막는다. 셸로 고친 파일까지 잡는 안전망 |

정규식은 후보만 좁히고 고칠지는 에이전트가 판단한다. 강제는 각 레포의 테스트(ArchUnit·Modulith)가 계속 맡는다. 같은 규칙은 시점마다 세션당 한 번만 뜬다.

## 설치

Python 3.10 이상과 git이 필요하다. 저장소가 private이므로 GitHub 접근이 되는 git 자격 증명이 있어야 한다(`gh auth login` 후 `gh auth setup-git`).

```bash
claude plugin marketplace add ticket-project/ticket-agent-rules
claude plugin install ticket-rules@ticket-agent-rules
```

기본 설치 범위는 사용자 전체다. 그래서 워크스페이스 루트처럼 레포 밖에서 연 세션에서도 동작한다.

### 자동 업데이트 켜기

Claude Code는 이 마켓플레이스의 자동 업데이트를 기본으로 꺼 둔다. 한 번 켜 두면 세션 시작 뒤 백그라운드로 새 커밋을 받는다.

`/plugin` → Marketplaces → `ticket-agent-rules` → Enable auto-update

켜지 않으면 `/plugin marketplace update ticket-agent-rules`로 직접 받는다. 플러그인에 `version`을 두지 않았으므로 커밋마다 새 버전으로 본다.

## 규칙 추가·수정

1. `plugins/ticket-rules/scripts/`에 스크립트를 추가하거나 고친다. 입출력·세션당 한 번·발동 기록은 `common.py`를 쓴다.
2. 새 스크립트는 `plugins/ticket-rules/hooks/hooks.json`의 알맞은 시점에 등록한다.
3. `python plugins/ticket-rules/tests/test_rules.py`와 `claude plugin validate .`를 통과시킨다.
4. 대상 레포 코드 전체에 돌려 오탐이 없는지 본다.

새 규칙은 "반복해서 틀리는가 → 코드로 판정되는가 → 예외가 있는가(없으면 테스트로 강제) → 파일 하나로 판정되는가(작성 직후) / 여러 파일을 봐야 하는가(끝내기 직전)" 순서로 둘 곳을 정한다.

## 발동 기록

`~/.claude/ticket-rules/fired.log`에 한 줄씩 남는다. 시각, 세션, 레포, 시점(`PostToolUse`·`Stop`), 규칙, 걸린 참조가 들어간다. 자주 뜨는데 고쳐지지 않는 규칙은 오탐을 의심한다.

## 한계

- Claude Code 세션에서만 동작한다. Codex 등 다른 도구, 사람이 쓴 코드, CI에는 적용되지 않는다.
- 셸 명령으로 고친 파일은 작성 직후 hook을 거치지 않는다. 모듈 경계 규칙은 끝내기 직전 검사가 없어 각 레포의 테스트가 잡는다.
- 참고: [토스뱅크, AI가 팀 규칙을 지키도록 하는 방법](https://toss.tech/article/52631)

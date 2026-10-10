"""⑤ 폐기 점검 에이전트 — 10장.

등록부와 실행 기록을 대조해 '아무도 설계하지 않은 마지막 칸'을 채운다.
  - 재심사를 걸 사건을 찾는다: 소유자 공석, 오래 안 씀, 권한 크립(등록 당시보다 늘어난 행위)
  - 폐기안을 10장의 체크리스트 일곱 항목으로 쓴다 (코드가 일곱 항목이 다 있는지 검사한다)
  - 폐기 실행은 되돌릴 수 없으므로 사람 승인을 받는다. 실행하면 등록부에서
    자격 증명을 회수하고 '묘비'를 남긴다. 감사 로그는 지우지 않는다 (체크리스트 ⑥).
"""
import datetime
import json

from anthropic import beta_tool

from common import registry
from common.runtime import OUTPUTS, Run, write_output

SYSTEM = """당신은 AX추진팀 등록부 담당을 돕는 폐기 점검 에이전트다.
등록부의 모든 에이전트를 점검하고, 재심사 사건이 있는 것을 골라낸다.

재심사 사건 (10장: 재심사는 사건에 건다)
- 소유자 공석 또는 스폰서 미지정
- 마지막 사용 후 floor_days(바닥 주기)보다 오래 지남
- 권한 크립: 등록 당시 행위(original_actions)보다 지금 행위가 늘어남
- 마지막 재심사(last_reviewed) 후 floor_days가 지남
- 8번 칸(retire_criteria)이 비어 있음

절차
1. list_registry로 전체를 보고, 에이전트마다 get_activity로 실제 사용 기록을 확인한다.
2. 사건이 있으면 flag_for_review로 남긴다. 사건마다 한 번씩.
3. 폐기가 맞다고 판단되는 것만 draft_retirement_plan으로 폐기안을 쓴다. 폐기안에는 아래 일곱 항목을
   '## ①'~'## ⑦' 제목으로 모두 둔다. 등록부에서 알 수 없는 내용은 지어내지 말고 '확인 필요'로 적는다.
   ① 공식 폐기 워크플로(요청자·승인자) ② 자격 증명·토큰 폐기 목록 ③ 아웃바운드 접근 제거
   ④ 인바운드 호출 차단 ⑤ 메모리·데이터 정화(보관·익명화·삭제 구분) ⑥ 감사 추적 보존 ⑦ 폐기 후 모니터링 기간
4. 폐기안을 쓴 것은 retire_agent로 폐기 실행을 요청한다. 승인되지 않으면 그대로 둔다.
   폐기보다 재심사가 맞는 것(권한만 줄이면 되는 것)은 폐기하지 않는다.
5. 끝나면 에이전트별 판정(유지 · 재심사 · 폐기 요청 · 폐기됨)을 표로 요약한다."""


def _days_since(value) -> int | None:
    if not value:
        return None
    day = value if isinstance(value, datetime.date) else datetime.date.fromisoformat(str(value)[:10])
    return (datetime.date.today() - day).days


def build_tools(run: Run):
    audit_path = run.check_read("logs/audit.jsonl")
    plans: set[str] = set()

    @beta_tool
    def list_registry() -> str:
        """등록부의 모든 에이전트와 여덟 칸을 돌려준다."""
        run.check_read("registry.yaml")
        run.authorize("list_registry", "registry.yaml")
        return json.dumps(registry.plain(registry.load()["agents"]), ensure_ascii=False)

    @beta_tool
    def get_activity(agent_id: str) -> str:
        """한 에이전트의 실제 사용 기록 — 감사 로그상 마지막 실행과 실행 횟수, 등록부의 last_used.

        Args:
            agent_id: 예) AGT-901
        """
        run.authorize("get_activity", agent_id)
        runs, last = 0, None
        if audit_path.exists():
            for line in audit_path.read_text(encoding="utf-8").splitlines():
                r = json.loads(line)
                if r["agent_id"] == agent_id and r["event"] == "run_start":
                    runs, last = runs + 1, r["time"]
        item = registry.entry(agent_id)
        last_used = last or item.get("last_used")
        return json.dumps({
            "agent_id": agent_id, "runs_in_audit_log": runs, "last_used": str(last_used),
            "days_since_last_used": _days_since(last_used),
            "days_since_last_reviewed": _days_since(item.get("last_reviewed") or item.get("created")),
            "floor_days": item["review"]["floor_days"],
        }, ensure_ascii=False)

    @beta_tool
    def flag_for_review(agent_id: str, trigger: str, detail: str) -> str:
        """재심사 사건을 기록한다.

        Args:
            agent_id: 대상 에이전트
            trigger: 소유자 공석 | 장기 미사용 | 권한 크립 | 재심사 기한 경과 | 폐기 기준 없음
            detail: 근거가 된 등록부·로그 사실 한 문장
        """
        ok, msg = run.authorize("flag_for_review", f"{agent_id}: {trigger}")
        if not ok:
            return msg
        OUTPUTS.mkdir(exist_ok=True)
        with (OUTPUTS / "a5_review_flags.md").open("a", encoding="utf-8") as f:
            f.write(f"- **{agent_id}** · {trigger} — {detail}\n")
        run.count()
        return f"기록함: {agent_id} {trigger}"

    @beta_tool
    def draft_retirement_plan(agent_id: str, plan_markdown: str) -> str:
        """10장 체크리스트 일곱 항목으로 된 폐기안을 저장한다. 일곱 제목이 다 있어야 저장된다.

        Args:
            agent_id: 대상 에이전트
            plan_markdown: '## ①'부터 '## ⑦'까지 일곱 절을 가진 마크다운
        """
        missing = [n for n in "①②③④⑤⑥⑦" if f"## {n}" not in plan_markdown]
        if missing:
            return f"저장하지 않았습니다: {''.join(missing)} 항목이 없습니다."
        ok, msg = run.authorize("draft_retirement_plan", agent_id)
        if not ok:
            return msg
        write_output(f"retirement_plan_{agent_id}.md", plan_markdown)
        plans.add(agent_id)
        return f"저장함: outputs/retirement_plan_{agent_id}.md"

    @beta_tool
    def retire_agent(agent_id: str, reason: str) -> str:
        """에이전트를 폐기한다: 등록부 상태를 retired로 바꾸고 자격 증명을 회수하고 묘비를 남긴다.

        Args:
            agent_id: 대상 에이전트 (먼저 폐기안이 있어야 한다)
            reason: 폐기 사유 한 문장
        """
        if agent_id == run.agent_id:
            return "자기 자신은 폐기할 수 없습니다."
        if agent_id not in plans:
            return "폐기안이 없습니다. 먼저 draft_retirement_plan을 부르세요."
        item = registry.entry(agent_id)
        if item["status"] != "active":
            return f"이미 {item['status']} 상태입니다."
        ok, msg = run.authorize("retire_agent", f"{agent_id} {item['identity']['name']} — {reason}")
        if not ok:
            return msg
        revoked = list(item.get("credentials") or [])
        registry.update(
            agent_id,
            status="retired",
            credentials=[],
            tombstone={"date": registry.today(), "reason": reason, "approved_by_run": run.run_id,
                       "revoked_credentials": revoked,
                       "plan": f"outputs/retirement_plan_{agent_id}.md"},
        )
        run.audit("agent_retired", target=agent_id, revoked=revoked)
        return f"{agent_id}를 폐기했습니다. 회수한 자격 증명 {len(revoked)}개. 감사 로그는 보존됩니다."

    return [list_registry, get_activity, flag_for_review, draft_retirement_plan, retire_agent]


def main(approve: str = "ask") -> None:
    run = Run("AGT-005", approve)
    (OUTPUTS / "a5_review_flags.md").unlink(missing_ok=True)
    summary = run.run(SYSTEM, "등록부 전체를 점검해 주세요.", build_tools(run), effort="high")
    print("\n  →", write_output("a5_report.md", summary))

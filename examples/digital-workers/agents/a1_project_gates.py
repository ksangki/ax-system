"""① AI 과제 판별 에이전트 — 1·2장.

현업이 올린 'AI 과제' 목록을 2장의 관문 다섯 개에 차례로 세워
이름표뿐인 과제와 진짜 에이전트 후보를 가른다. 판정은 초안이고,
확정은 사람이 보고서를 읽고 한다 (등록부 5번 칸).
"""
import csv
import json

from anthropic import beta_tool

from common.runtime import OUTPUTS, Run, write_output

SYSTEM = """당신은 AX추진팀의 재고 조사 담당을 돕는 판별 에이전트다.
현업이 'AI 과제'라고 올린 항목을 아래 관문에 순서대로 세운다. 통과한 것만 다음 관문으로 보낸다.

① 생성형인가 — 규칙 기반 자동화·통계 모델·기존 배치 작업을 거른다. 걸러진 것에도 값이 있다고 적는다.
② 행위하는가 — 결과물이 사람 손을 거치지 않고 다음 단계로 넘어가는가. 답만 하는 챗봇·초안 도구는 여기서 갈린다.
③ 산출물이 실재하는가 — 기획안만 있는 것, 다른 것이 올라탈 토대 인프라(별도 인프라 목록으로 뺀다)를 거른다.
④ 조직의 업무인가 — 팀의 업무와 목표에 연결되는가. 개인 편의 도구는 대상이 아니다(없애라는 뜻은 아니다).
⑤ 무게가 있는가 — 되돌릴 수 없는 일, 돈·대외 커뮤니케이션·민감정보를 건드리는가.
   ①~④는 대상 여부를, ⑤는 대상 안에서 통제 강도를 가른다.

등록 등급은 다음 넷 중 하나로 정한다.
- 대상 아님: ①~④ 중 하나에서 떨어짐
- 가볍게 등록만: ④까지 통과했지만 실제로 행동하지 않음
- 등록 + 모니터링: 행동하지만 되돌릴 수 있음
- 정식 등록 + 강한 통제: 행동하고, 되돌릴 수 없거나 돈·대외·민감정보에 닿음

규칙
- 항목마다 record_verdict를 한 번씩 부른다. 판단 근거는 과제 설명에 적힌 사실에서만 가져온다.
- 설명만으로 판정이 갈리면 지어내지 말고 hold=true로 판정 보류한다. 보류 사유에 무엇을 물어야 하는지 적는다.
- 모두 기록한 뒤, 떨어진 항목을 사유별로 묶은 요약을 한국어 마크다운으로 쓴다.
  "목록이 줄어든 것은 초점이 생겼다는 뜻"이 읽히도록, 몇 건이 어디서 왜 떨어졌는지를 표로 보인다."""

VERDICTS = OUTPUTS / "a1_verdicts.jsonl"


def build_tools(run: Run):
    @beta_tool
    def list_projects() -> str:
        """현업이 제출한 AI 과제 목록 전체를 JSON으로 돌려준다."""
        path = run.check_read("data/projects.csv")
        run.authorize("list_projects", "과제 목록 읽기")
        with path.open(encoding="utf-8") as f:
            return json.dumps(list(csv.DictReader(f)), ensure_ascii=False)

    @beta_tool
    def record_verdict(project_id: str, last_gate_passed: int, tier: str,
                       reason: str, hold: bool = False) -> str:
        """과제 하나의 관문 판정을 기록한다.

        Args:
            project_id: 과제 ID (예: P03)
            last_gate_passed: 마지막으로 통과한 관문 번호 0~5 (①에서 떨어지면 0)
            tier: 대상 아님 | 가볍게 등록만 | 등록 + 모니터링 | 정식 등록 + 강한 통제
            reason: 떨어진 관문 또는 등급의 근거 한두 문장
            hold: 설명만으로 판정할 수 없어 보류하면 true
        """
        tiers = {"대상 아님", "가볍게 등록만", "등록 + 모니터링", "정식 등록 + 강한 통제"}
        if tier not in tiers or not 0 <= last_gate_passed <= 5:
            return f"형식 오류: tier는 {sorted(tiers)} 중 하나, last_gate_passed는 0~5여야 합니다."
        ok, msg = run.authorize("record_verdict", f"{project_id} → {tier}")
        if not ok:
            return msg
        record = {"project_id": project_id, "last_gate_passed": last_gate_passed,
                  "tier": tier, "reason": reason, "hold": hold, "run_id": run.run_id}
        OUTPUTS.mkdir(exist_ok=True)
        with VERDICTS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        run.count()
        return f"기록함: {project_id}"

    return [list_projects, record_verdict]


def main(approve: str = "ask") -> None:
    run = Run("AGT-001", approve)
    VERDICTS.unlink(missing_ok=True)
    report = run.run(SYSTEM, "과제 목록을 읽고 전 항목을 판정한 뒤 요약 보고서를 써 주세요.",
                     build_tools(run))
    print("\n  →", write_output("a1_report.md", report))

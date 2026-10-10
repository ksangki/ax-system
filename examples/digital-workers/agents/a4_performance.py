"""④ 성과 측정 에이전트 — 6·8·9장.

계산은 코드가, 해석은 모델이 한다. FTE 환산식(8장)은 compute_fte 안에 고정돼 있고,
모델은 그 결과를 읽고 보고서를 쓸 뿐 숫자를 만들지 않는다.
성과 숫자가 모델의 문장 생성에 따라 흔들리면 그 숫자는 근거가 될 수 없기 때문이다.

재료는 ①~③이 남긴 logs/usage.jsonl(실제 API 비용과 처리 건수)과 data/baselines.yaml이다.
"""
import collections
import json

import yaml
from anthropic import beta_tool

from common.runtime import Run, write_output

SYSTEM = """당신은 AX추진팀 성과 담당을 돕는 성과 측정 에이전트다.
숫자는 compute_fte가 돌려준 값만 쓴다. 직접 계산하거나 반올림을 바꾸지 않는다.

보고서 순서 (한국어 마크다운)
1. 사용 제한 선언 — 맨 앞에 둔다: "이 숫자는 정원 감축이나 개인 평가의 근거로 쓰지 않는다.
   절감분은 (재투자 · 품질 향상 · 업무량 흡수) 중 어디에 쓸지 별도로 정한다." (8·9장)
2. 기준선 — 무엇과 비교했는지 baselines의 baseline 값을 그대로 밝힌다.
3. 에이전트별 표 — 처리 건수, 실행 비용, 건당 비용, 월 환산 FTE(1단), 신뢰도·자율성 계수, 인정 FTE(2단), 월 API 비용
4. 해석 — 1단과 2단의 차이가 어디서 왔는지(신뢰도인지 자율성인지) 에이전트마다 한 문장
5. 정직하게 남길 것 — 표본이 작다는 것, 가상 기준값이라는 것, 자기보고 등급의 폐지 시한,
   승인 게이트가 자율성 계수를 낮춘다는 것(그것이 통제의 값이라는 것)을 적는다.
과장하는 형용사를 쓰지 않는다."""


def usage_by_agent(run: Run) -> dict:
    path = run.check_read("logs/usage.jsonl")
    totals = collections.defaultdict(lambda: {"runs": 0, "items": 0, "human_touches": 0, "cost_usd": 0.0})
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            t = totals[r["agent_id"]]
            t["runs"] += 1
            t["items"] += r["items"]
            t["human_touches"] += r["human_touches"]
            t["cost_usd"] += r["cost_usd"]
    return dict(totals)


def fte(base: dict, agent: dict, used: dict) -> dict:
    """8장의 두 단 환산. 이 함수가 성과 숫자의 유일한 출처다."""
    items = used["items"]
    # 1단 — 사람이 했다면 걸렸을 시간을 FTE로
    monthly_hours = agent["monthly_volume"] * agent["human_minutes_per_item"] / 60
    stage1 = monthly_hours / base["fte_hours_per_month"]
    # 2단 — 두 계수를 곱해 인정할 몫을 정한다
    reliability = base["reliability"][agent["evidence"]]
    autonomy = 1.0 if items == 0 else max(0.0, 1 - used["human_touches"] / items)  # 사람 개입 없이 끝난 비율
    stage2 = stage1 * reliability * autonomy
    per_item = used["cost_usd"] / items if items else 0.0
    return {
        "task": agent["task"], "runs": used["runs"], "items": items,
        "cost_usd": round(used["cost_usd"], 4), "cost_per_item_usd": round(per_item, 4),
        "monthly_volume_assumed": agent["monthly_volume"],
        "stage1_fte": round(stage1, 2), "reliability": reliability, "evidence": agent["evidence"],
        "autonomy": round(autonomy, 2), "human_touches": used["human_touches"],
        "stage2_fte": round(stage2, 2),
        "monthly_api_cost_usd": round(per_item * agent["monthly_volume"], 2),
    }


def build_tools(run: Run):
    base = yaml.safe_load(run.check_read("data/baselines.yaml").read_text(encoding="utf-8"))

    @beta_tool
    def read_usage() -> str:
        """에이전트별 누적 실행 횟수·처리 건수·사람 승인 횟수·API 비용을 돌려준다."""
        run.authorize("read_usage", "logs/usage.jsonl")
        return json.dumps(usage_by_agent(run), ensure_ascii=False)

    @beta_tool
    def read_baselines() -> str:
        """FTE 기준시간, 신뢰도 등급표, 기준선, 에이전트별 건당 사람 소요시간을 돌려준다."""
        run.authorize("read_baselines", "data/baselines.yaml")
        return json.dumps(base, ensure_ascii=False)

    @beta_tool
    def compute_fte(agent_id: str) -> str:
        """한 에이전트의 두 단 FTE 환산을 계산한다. 보고서의 숫자는 이 결과만 쓴다.

        Args:
            agent_id: 예) AGT-003
        """
        if agent_id not in base["agents"]:
            return f"{agent_id}는 기준값이 없어 환산하지 않습니다."
        used = usage_by_agent(run).get(agent_id)
        if not used:
            return f"{agent_id}의 실행 기록이 없습니다. 먼저 그 에이전트를 실행하세요."
        ok, msg = run.authorize("compute_fte", agent_id)
        if not ok:
            return msg
        run.count()
        return json.dumps(fte(base, base["agents"][agent_id], used), ensure_ascii=False)

    return [read_usage, read_baselines, compute_fte]


def main(approve: str = "ask") -> None:
    run = Run("AGT-004", approve)
    report = run.run(SYSTEM, "실행 기록이 있는 에이전트의 성과를 환산해 월간 성과 보고서를 써 주세요.",
                     build_tools(run))
    print("\n  →", write_output("a4_performance_report.md", report))

"""예제 실행기.

    python run.py a1              # ① AI 과제 판별
    python run.py a2              # ② SOP 변환
    python run.py a3              # ③ 장애 티켓 1차 분석
    python run.py a4              # ④ 성과 측정
    python run.py a5              # ⑤ 폐기 점검 (승인 요청이 터미널에 뜬다)
    python run.py all --approve yes   # 다섯 개를 순서대로, 승인은 전부 '예'로

--approve ask|yes|no : 승인이 필요한 행위를 터미널에서 묻는다(기본) / 전부 승인 / 전부 거절
"""
import argparse
import importlib
import os
import sys

AGENTS = {
    "a1": "agents.a1_project_gates",
    "a2": "agents.a2_sop_converter",
    "a3": "agents.a3_incident_triage",
    "a4": "agents.a4_performance",
    "a5": "agents.a5_retirement",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("agent", choices=[*AGENTS, "all"])
    parser.add_argument("--approve", choices=["ask", "yes", "no"], default="ask")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY 환경 변수가 없습니다. 키는 코드나 파일에 적지 말고 환경 변수로 넘기세요.")

    for key in AGENTS if args.agent == "all" else [args.agent]:
        print(f"\n━━ {key} ━━")
        importlib.import_module(AGENTS[key]).main(args.approve)


if __name__ == "__main__":
    main()

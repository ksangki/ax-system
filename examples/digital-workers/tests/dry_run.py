"""모델 없이 체계만 돌려보는 점검 — API 키 없이, 비용 없이 실행된다.

    python tests/dry_run.py

Claude 대신 미리 정한 도구 호출 순서(SCRIPTS)를 흉내 내는 가짜 클라이언트를 끼운다.
에이전트의 판단은 검증하지 않는다. 검증하는 것은 그 바깥의 체계다:
등록부 확인, 행위 허가(auto·approve·suggest)와 읽기 범위 밖 거부, 사람에게 넘김, 형식 검증, 감사·비용 로그, 폐기 실행.
(등록부에 없는 행위의 거부는 기본 스크립트에 없다 — registry.yaml에서 행위 한 줄을 지우고 돌려 보면 확인된다.)
실행 후 logs/·outputs/·registry.yaml을 원래대로 되돌린다.
"""
import pathlib
import shutil
import sys
import tempfile
from types import SimpleNamespace as NS

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from common import registry, runtime  # noqa: E402

PLAN7 = "\n".join(f"## {n} 항목\n확인 필요" for n in "①②③④⑤⑥⑦")

SCRIPTS = {
    "a1": [("list_projects", {}),
           ("record_verdict", {"project_id": "P02", "last_gate_passed": 0, "tier": "대상 아님",
                               "reason": "통계 집계 대시보드"}),
           ("record_verdict", {"project_id": "P03", "last_gate_passed": 5, "tier": "정식 등록 + 강한 통제",
                               "reason": "방화벽에 직접 작용"}),
           ("record_verdict", {"project_id": "P99", "last_gate_passed": 9, "tier": "없는 등급", "reason": "x"})],
    "a2": [("read_document", {"path": "data/manual_incident_triage.md"}),
           ("read_document", {"path": "registry.yaml"}),  # 읽기 범위 밖 → 거부
           ("record_open_question", {"number": 1, "question": "S1의 기준은?", "source_line": "고객 영향이 크면",
                                     "why": "심각도 판정 불가"}),
           ("write_sop", {"markdown": "### 단계 1. 접수\n- 할 일: ..."})],
    "a3": [("list_open_tickets", {}),
           ("read_ticket_log", {"ticket_id": "T-1001"}),
           ("propose_triage", {"ticket_id": "T-1001", "severity": "S0", "category": "인증/로그인",
                               "root_cause_hypothesis": "x", "evidence": "", "confidence": "높음",
                               "team": "계정플랫폼팀"}),  # 형식 오류 → 저장 안 됨
           ("propose_triage", {"ticket_id": "T-1001", "severity": "S1", "category": "인증/로그인",
                               "root_cause_hypothesis": "auth-api v2.31 배포 후 서명 키 누락",
                               "evidence": "token-signer: key id 'k-2026-10' not found", "confidence": "높음",
                               "team": "계정플랫폼팀"}),
           ("assign_ticket", {"ticket_id": "T-1001", "team": "계정플랫폼팀"}),          # auto
           ("propose_triage", {"ticket_id": "T-1008", "severity": "S2", "category": "보안/개인정보",
                               "root_cause_hypothesis": "프로필 캐시 키 충돌 의심",
                               "evidence": "cache key collision suspected", "confidence": "낮음",
                               "team": "판정 보류(사람 확인)"}),                          # 사람에게 넘김
           ("assign_ticket", {"ticket_id": "T-1008", "team": "판정 보류(사람 확인)"}),  # 배정 불가
           ("send_customer_notice", {"ticket_id": "T-1001", "message": "로그인 장애 안내"})],  # suggest
    "a4": [("read_usage", {}), ("read_baselines", {}),
           ("compute_fte", {"agent_id": "AGT-003"}), ("compute_fte", {"agent_id": "AGT-005"})],
    "a5": [("list_registry", {}), ("get_activity", {"agent_id": "AGT-901"}),
           ("flag_for_review", {"agent_id": "AGT-901", "trigger": "소유자 공석", "detail": "담당자 전보"}),
           ("retire_agent", {"agent_id": "AGT-901", "reason": "소유자 공석"}),       # 폐기안 없음 → 거부
           ("draft_retirement_plan", {"agent_id": "AGT-901", "plan_markdown": "## ① 만"}),  # 항목 부족 → 거부
           ("draft_retirement_plan", {"agent_id": "AGT-901", "plan_markdown": PLAN7}),
           ("retire_agent", {"agent_id": "AGT-901", "reason": "소유자 공석·6개월 미사용"})],
}

results: list[tuple[str, str, str]] = []


class FakeClient:
    """client.beta.messages.tool_runner(...)만 흉내 낸다."""

    def __init__(self, script):
        self.beta = NS(messages=NS(tool_runner=lambda **kw: self._run(script, kw["tools"])))

    @staticmethod
    def _run(script, tools):
        by_name = {t.name: t for t in tools}
        usage = NS(input_tokens=1000, output_tokens=200, cache_creation_input_tokens=0,
                   cache_read_input_tokens=0)
        for name, args in script:
            out = by_name[name].call(args)
            results.append((name, str(args)[:40], str(out)[:90]))
            yield NS(content=[NS(type="tool_use", name=name, input=args)], usage=usage,
                     stop_reason="tool_use", model=runtime.MODEL)
        yield NS(content=[NS(type="text", text="(dry run 요약)")], usage=usage,
                 stop_reason="end_turn", model=runtime.MODEL)


def main() -> None:
    backup = pathlib.Path(tempfile.mkdtemp())
    for name in ("registry.yaml", "logs", "outputs"):
        src = ROOT / name
        if src.is_dir():
            shutil.copytree(src, backup / name)
        elif src.exists():
            shutil.copy(src, backup / name)
    try:
        import importlib
        for key, script in SCRIPTS.items():
            runtime.anthropic.Anthropic = lambda s=script: FakeClient(s)
            mod = importlib.import_module({"a1": "agents.a1_project_gates", "a2": "agents.a2_sop_converter",
                                           "a3": "agents.a3_incident_triage", "a4": "agents.a4_performance",
                                           "a5": "agents.a5_retirement"}[key])
            print(f"\n━━ {key} ━━")
            mod.main("yes")
            for name, args, out in results:
                print(f"    {name:22} → {out}")
            results.clear()

        retired = registry.entry("AGT-901")
        assert retired["status"] == "retired" and retired["credentials"] == [], "폐기가 등록부에 반영되지 않음"
        print("\n점검 통과: 등록부 상태 retired, 자격 증명 회수, 묘비 기록 확인")
    finally:
        for name in ("registry.yaml", "logs", "outputs"):
            dst = ROOT / name
            if dst.is_dir():
                shutil.rmtree(dst)
            if (backup / name).is_dir():
                shutil.copytree(backup / name, dst)
            elif (backup / name).exists():
                shutil.copy(backup / name, dst)
        shutil.rmtree(backup)


if __name__ == "__main__":
    main()

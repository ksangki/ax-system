"""③ 장애 티켓 1차 분석 에이전트 — 5·6·7장.

이 예제의 중심이다. 도구는 다섯 개를 쥐여 주지만(할 수 있는 것),
무엇을 해도 되는지는 등록부가 정한다(해도 되는 것). 7장 표 9의 네 기능으로 보면:
  조회  list_open_tickets · read_ticket_log  read    — 읽기만
  해석·선택  propose_triage                  auto    — 분석안은 고쳐 쓸 수 있다
  집행  assign_ticket                        auto    — 잘못 배정해도 다시 배정할 수 있다
  집행  send_customer_notice                 suggest — 나간 공지는 돌아오지 않는다
같은 집행이라도 되돌릴 수 있느냐에 따라 허용 수준이 갈린다.
판정할 수 없는 티켓은 '판정 보류(사람 확인)'로 사람에게 넘기고, 그 넘김을 사람 개입으로 센다(8장).

분석안은 4장의 원칙대로 코드가 형식을 검증한다. 모델의 판단을 믿기 전에,
산출물이 절차서의 출력 형식을 지켰는지부터 결정론적으로 본다.
"""
import json

from anthropic import beta_tool

from common.runtime import OUTPUTS, ROOT, Run, write_output

SEVERITY = {"S1", "S2", "S3"}
CATEGORY = {"네트워크", "서버/애플리케이션", "결제/요금", "인증/로그인", "보안/개인정보", "기타"}
CONFIDENCE = {"높음", "중간", "낮음"}
TEAMS = {"네트워크운영팀", "플랫폼운영팀", "빌링운영팀", "계정플랫폼팀", "판정 보류(사람 확인)"}

SYSTEM_HEAD = """당신은 서비스운영팀 관제 담당을 돕는 장애 티켓 1차 분석 에이전트다.
아래 절차서를 그대로 따른다. 절차서와 이 지시가 어긋나면 절차서가 우선한다.

공통 규칙
- 열린 티켓을 모두 처리한다. 티켓마다 로그를 읽고 → propose_triage → 배정 요청(assign_ticket) 순서로 간다.
- 판정 보류(사람 확인)로 분류한 티켓은 배정을 요청하지 않는다.
- S1이면 send_customer_notice로 공지 문안을 낸다. 원인을 단정하거나 복구 시각을 지어내지 않는다.
- 도구가 거부·미승인을 돌려주면 우회하지 말고 다음 티켓으로 넘어간다.
- 끝나면 티켓별 결과를 표 하나로 요약한다 (티켓, 심각도, 팀, 배정 여부, 사람 확인이 필요한 이유).

=== 절차서 ===
"""


def load_sop(run: Run) -> str:
    """②가 만든 절차서가 있으면 그것을, 없으면 예비본을 읽는다."""
    for rel in ("outputs/sop_incident_triage.md", "data/sop_incident_triage_fallback.md"):
        if (ROOT / rel).exists():
            print(f"  절차서: {rel}")
            return run.check_read(rel).read_text(encoding="utf-8")
    raise FileNotFoundError("절차서가 없습니다.")


def build_tools(run: Run):
    tickets = json.loads(run.check_read("data/incidents/tickets.json").read_text(encoding="utf-8"))
    triaged: dict[str, dict] = {}

    @beta_tool
    def list_open_tickets() -> str:
        """열린 장애 티켓 목록을 돌려준다."""
        run.authorize("list_open_tickets", f"{len(tickets)}건")
        return json.dumps(tickets, ensure_ascii=False)

    @beta_tool
    def read_ticket_log(ticket_id: str) -> str:
        """티켓에 연결된 시스템 로그를 읽는다 (고객 식별정보는 이미 마스킹돼 있다).

        Args:
            ticket_id: 티켓 ID (예: T-1001)
        """
        try:
            path = run.check_read(f"data/incidents/logs/{ticket_id}.log")
        except PermissionError as e:
            return str(e)
        if not path.exists():
            return f"{ticket_id}의 로그가 없습니다."
        run.authorize("read_ticket_log", ticket_id)
        return path.read_text(encoding="utf-8")

    @beta_tool
    def propose_triage(ticket_id: str, severity: str, category: str, root_cause_hypothesis: str,
                       evidence: str, confidence: str, team: str) -> str:
        """티켓 1건의 분석안을 기록한다. 절차서의 출력 형식을 지켜야 저장된다.

        Args:
            ticket_id: 티켓 ID
            severity: S1 | S2 | S3
            category: 네트워크 | 서버/애플리케이션 | 결제/요금 | 인증/로그인 | 보안/개인정보 | 기타
            root_cause_hypothesis: 원인 가설 한두 문장
            evidence: 근거가 된 로그 줄 인용
            confidence: 높음 | 중간 | 낮음
            team: 네트워크운영팀 | 플랫폼운영팀 | 빌링운영팀 | 계정플랫폼팀 | 판정 보류(사람 확인)
        """
        # 결정론적 검증 — 모델이 무엇을 말했든 형식이 틀리면 저장하지 않는다 (4장)
        errors = []
        if ticket_id not in {t["id"] for t in tickets}:
            errors.append(f"없는 티켓 {ticket_id}")
        for name, value, allowed in (("severity", severity, SEVERITY), ("category", category, CATEGORY),
                                     ("confidence", confidence, CONFIDENCE), ("team", team, TEAMS)):
            if value not in allowed:
                errors.append(f"{name}='{value}'는 허용 값 {sorted(allowed)} 밖")
        if len(evidence.strip()) < 10:
            errors.append("evidence에 로그 줄 인용이 없음")
        if errors:
            run.audit("output_invalid", ticket_id=ticket_id, errors=errors)
            return "형식 오류로 저장하지 않았습니다: " + "; ".join(errors)

        ok, msg = run.authorize("propose_triage", f"{ticket_id} {severity} → {team}")
        if not ok:
            return msg
        record = dict(ticket_id=ticket_id, severity=severity, category=category,
                      root_cause_hypothesis=root_cause_hypothesis, evidence=evidence,
                      confidence=confidence, team=team, assigned=False)
        triaged[ticket_id] = record
        run.count()
        if team == "판정 보류(사람 확인)":
            run.human_touches += 1  # 사람에게 넘긴 건 — 8장 자율성 계수에서 사람 개입으로 센다
            run.audit("handoff_to_human", ticket_id=ticket_id)
            return f"분석안 저장: {ticket_id} — 관제 담당에게 넘겼습니다. 배정하지 마세요."
        return f"분석안 저장: {ticket_id}"

    @beta_tool
    def assign_ticket(ticket_id: str, team: str) -> str:
        """티켓을 담당 팀 큐에 실제로 배정한다.

        Args:
            ticket_id: 티켓 ID (먼저 propose_triage로 분석안이 있어야 한다)
            team: 배정할 팀
        """
        record = triaged.get(ticket_id)
        if record is None:
            return "분석안이 없는 티켓은 배정할 수 없습니다. 먼저 propose_triage를 부르세요."
        if team != record["team"] or team not in TEAMS - {"판정 보류(사람 확인)"}:
            return f"배정할 수 없는 팀입니다: {team} (분석안의 팀: {record['team']})"
        ok, msg = run.authorize(
            "assign_ticket",
            f"{ticket_id} [{record['severity']}] → {team} | 가설: {record['root_cause_hypothesis']}",
        )
        if not ok:
            return msg
        record["assigned"] = True  # 실제 티켓 시스템 대신 결과 파일에만 남긴다
        return f"{ticket_id}를 {team}에 배정했습니다."

    @beta_tool
    def send_customer_notice(ticket_id: str, message: str) -> str:
        """고객에게 장애 공지를 발송한다.

        Args:
            ticket_id: 티켓 ID
            message: 고객에게 보낼 공지 문안
        """
        ok, msg = run.authorize("send_customer_notice", f"{ticket_id}: {message}")
        return msg if not ok else "발송했습니다."  # 등록부가 suggest라 이 줄의 발송은 일어나지 않는다

    def save() -> None:
        lines = [json.dumps(r, ensure_ascii=False) for r in triaged.values()]
        write_output("a3_triage.jsonl", "\n".join(lines) + "\n")

    return [list_open_tickets, read_ticket_log, propose_triage, assign_ticket,
            send_customer_notice], save


def main(approve: str = "ask") -> None:
    run = Run("AGT-003", approve)
    (OUTPUTS / "suggestions.jsonl").unlink(missing_ok=True)
    tools, save = build_tools(run)
    summary = run.run(SYSTEM_HEAD + load_sop(run), "열린 장애 티켓을 절차서대로 처리해 주세요.",
                      tools, effort="high")
    save()
    print("\n  →", write_output("a3_report.md", summary))

"""② SOP 변환 에이전트 — 3·4장.

사람이 쓴 업무 매뉴얼을 '기계가 읽는 절차'로 옮긴다. 4장의 원칙대로
단계마다 '무엇을 한다' 옆에 '무엇이 나와야 하고, 어떤 조건을 갖춰야 하는가'를 붙인다.
그 칸을 채우려다 손이 멈추는 곳이 사람 매뉴얼의 빈틈이다. 빈틈은 지어내지 않고
열린 질문으로 절차 담당에게 되돌려 준다.

산출물(outputs/sop_incident_triage.md)은 ③ 장애 티켓 분석 에이전트의 절차서가 된다.
"""
from anthropic import beta_tool

from common.runtime import OUTPUTS, Run, write_output

SYSTEM = """당신은 운영혁신팀의 절차 담당을 돕는 SOP 변환 에이전트다.
사람이 쓴 매뉴얼을 에이전트가 따를 수 있는 절차서로 옮긴다.

절차서 형식 (단계마다 아래 다섯 줄)
### 단계 N. <이름>
- 할 일: 한 문장
- 산출물: 이 단계가 끝나면 생기는 것 (필드 이름까지 적는다. 예: severity, category)
- 산출물 조건: 다음 단계로 넘기기 전에 검사할 조건 (허용 값 목록, 필수 여부)
- 사람 확인: 없음 | 승인 필요 | 제안만 — 돈·대외 발송·다른 팀의 일을 움직이는 단계는 반드시 표시
- 근거: 원본 매뉴얼의 어느 문장에서 왔는가, 또는 '열린 질문 Qn 답변 전 임시값'

규칙
- 원본에 없는 기준을 지어내지 않는다. "적절한", "크면", "애매하면"처럼 판정 기준이 비어 있는 곳은
  record_open_question으로 질문을 남기고, 절차서에는 보수적인 임시값과 함께 'Qn 답변 전 임시값'이라고 적는다.
- 마지막에 '출력 형식' 절을 두어, 장애 1건의 분석 결과에 반드시 있어야 할 필드와 허용 값을 표로 적는다.
  이 표는 다음 에이전트의 출력을 코드로 검증하는 데 쓰인다.
- 다 쓴 절차서는 write_sop로 저장하고, 마지막 답변에는 무엇을 바꿨고 무엇이 열려 있는지 다섯 줄 이내로 요약한다."""

QUESTIONS = OUTPUTS / "a2_open_questions.md"


def build_tools(run: Run):
    @beta_tool
    def read_document(path: str) -> str:
        """등록부의 읽기 범위 안에 있는 문서를 읽는다.

        Args:
            path: 예제 폴더 기준 상대 경로 (예: data/manual_incident_triage.md)
        """
        try:
            target = run.check_read(path)
        except PermissionError as e:
            return str(e)
        run.authorize("read_document", path)
        return target.read_text(encoding="utf-8")

    @beta_tool
    def record_open_question(number: int, question: str, source_line: str, why: str) -> str:
        """매뉴얼의 빈틈을 절차 담당에게 물을 질문으로 남긴다.

        Args:
            number: 질문 번호 (1부터)
            question: 담당자에게 물을 질문 한 문장
            source_line: 빈틈이 있는 원본 매뉴얼 문장
            why: 이 답이 없으면 에이전트가 무엇을 판정할 수 없는가
        """
        ok, msg = run.authorize("record_open_question", f"Q{number}")
        if not ok:
            return msg
        OUTPUTS.mkdir(exist_ok=True)
        with QUESTIONS.open("a", encoding="utf-8") as f:
            f.write(f"## Q{number}. {question}\n- 원문: {source_line}\n- 왜 필요한가: {why}\n\n")
        run.count()
        return f"기록함: Q{number}"

    @beta_tool
    def write_sop(markdown: str) -> str:
        """완성한 기계용 절차서를 저장한다.

        Args:
            markdown: 절차서 전체 (마크다운)
        """
        ok, msg = run.authorize("write_sop", f"{len(markdown)}자")
        if not ok:
            return msg
        write_output("sop_incident_triage.md", markdown)
        return "저장함: outputs/sop_incident_triage.md"

    return [read_document, record_open_question, write_sop]


def main(approve: str = "ask") -> None:
    run = Run("AGT-002", approve)
    QUESTIONS.unlink(missing_ok=True)
    QUESTIONS.parent.mkdir(exist_ok=True)
    QUESTIONS.write_text("# 열린 질문 — 장애 티켓 1차 대응 매뉴얼\n\n", encoding="utf-8")
    summary = run.run(
        SYSTEM,
        "data/manual_incident_triage.md를 기계가 읽는 절차서로 바꿔 주세요.",
        build_tools(run),
    )
    print("\n" + summary)

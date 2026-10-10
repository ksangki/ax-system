# 장애 티켓 1차 대응 절차서 (기계용)

원본: data/manual_incident_triage.md (서비스운영팀, 2024년 개정)
열린 질문: Q1~Q9. 답이 오기 전까지 해당 단계는 표시된 임시값으로 운영한다. 임시값은 모두 '사람에게 넘기는 쪽'으로 잡았다.

공통 규칙
- 에이전트는 대외 발송(고객 공지)을 직접 하지 않는다. 다른 팀 배정은 제안만 하고 사람이 확정한다.
- 판정 근거가 없으면 값을 지어내지 않고 `unknown`(또는 `불명`)으로 둔 뒤 `escalation_needed = true`로 표시한다.

---

### 단계 1. 접수
- 할 일: 관제 화면에 새로 뜬 티켓을 바로 열어 티켓 식별 정보를 기록한다.
- 산출물: ticket_id, received_at, ticket_summary
- 산출물 조건: ticket_id 필수(빈 값 금지), received_at 필수(ISO 8601), ticket_summary 필수(티켓 본문 요약, 빈 값 금지)
- 사람 확인: 없음
- 근거: 원본 1절 "관제 화면에 새 티켓이 뜨면 바로 연다."

### 단계 2. 로그 확인
- 할 일: 티켓 내용과 관련된 로그를 조회해 에러를 추린다.
- 산출물: logs_checked, log_sources, log_time_range, error_summary
- 산출물 조건: logs_checked ∈ {true, false} 필수. true이면 log_sources(1개 이상)와 log_time_range(시작~끝) 필수. error_summary 필수(에러가 없으면 "에러 없음"). 임시로 log_time_range는 티켓 발생 시각을 반드시 포함해야 하며, 조회 대상은 티켓에 언급된 시스템 전부로 한다.
- 사람 확인: 없음
- 근거: 원본 1절 "티켓 내용과 관련 로그를 확인한다." / 로그 출처·범위는 열린 질문 Q9 답변 전 임시값

### 단계 3. 심각도 판정
- 할 일: 고객 영향 범위를 판단해 심각도를 S1/S2/S3 중 하나로 제안한다.
- 산출물: affected_scope, severity, severity_basis, severity_needs_review
- 산출물 조건:
  - affected_scope ∈ {전체_또는_다수, 일부, 거의_없음, 불명} 필수
  - severity ∈ {S1, S2, S3} 필수
  - 대응 규칙: 전체_또는_다수 → S1, 일부 → S2, 거의_없음 → S3
  - 임시값: affected_scope = 불명이거나 두 등급 사이에서 판단이 갈리면 **더 높은 등급**을 고르고 severity_needs_review = true
  - severity_basis 필수(판단에 쓴 사실, 빈 값 금지)
  - severity_needs_review ∈ {true, false} 필수. Q1·Q2 답변 전에는 S1과 S2 판정을 모두 true로 둔다.
- 사람 확인: 제안만 (severity_needs_review = true면 단계 4로 넘김)
- 근거: 원본 2절 "고객 영향이 크면 심각(S1)으로 본다." "일부 고객만 영향이 있으면 S2, 영향이 거의 없으면 S3로 둔다." / 수치 경계는 열린 질문 Q1·Q2 답변 전 임시값

### 단계 4. 심각도 에스컬레이션
- 할 일: severity_needs_review = true인 티켓을 선임에게 넘겨 심각도 확정을 요청한다.
- 산출물: escalation_needed, escalation_reason, severity_confirmed_by
- 산출물 조건: escalation_needed ∈ {true, false} 필수. true이면 escalation_reason 필수. severity_confirmed_by는 사람이 확정하면 확정자 식별자, 확정 전이면 "미확정". 확정 전에도 다음 단계는 단계 3의 (높게 잡은) severity로 진행한다.
- 사람 확인: 승인 필요
- 근거: 원본 2절 "애매하면 선임에게 물어본다." / '애매함'의 조건과 선임·채널·응답 시한은 열린 질문 Q3 답변 전 임시값(애매함 = severity_needs_review = true)

### 단계 5. 원인 추정
- 할 일: 로그의 에러와 최근 배포 이력을 바탕으로 원인 범주와 가설을 적는다.
- 산출물: recent_deploy, deploy_id, minutes_since_deploy, cause_category, cause_hypothesis, cause_confidence
- 산출물 조건:
  - recent_deploy ∈ {yes, no, unknown} 필수. 임시로 장애 발생 전 24시간 안에 배포 기록이 있으면 yes로 둔다.
  - recent_deploy = yes이면 deploy_id와 minutes_since_deploy(정수, 배포→장애 발생 분) 필수
  - cause_category ∈ {network, platform_app, billing, auth, unknown} 필수
  - cause_hypothesis 필수(근거가 된 로그 항목을 함께 적는다)
  - cause_confidence ∈ {확인됨, 추정, 불명} 필수. 배포만을 근거로 한 원인은 '확인됨'으로 둘 수 없고 최대 '추정'까지만 허용한다.
- 사람 확인: 없음
- 근거: 원본 3절 "로그에서 에러를 찾아 원인을 추정한다." "최근 배포가 있었는지 확인한다. 배포 직후 장애는 대부분 배포가 원인이다." / '직후'의 시간 범위와 확정 여부는 열린 질문 Q4 답변 전 임시값

### 단계 6. 담당 팀 배정 제안
- 할 일: 원인 범주에 맞는 담당 팀을 정해 배정안을 낸다.
- 산출물: assigned_team, assignment_status, assignment_reason
- 산출물 조건:
  - 대응 규칙: network → 네트워크운영팀, platform_app → 플랫폼운영팀, billing → 빌링운영팀, auth → 계정플랫폼팀, unknown → 플랫폼운영팀
  - assigned_team ∈ {네트워크운영팀, 플랫폼운영팀, 빌링운영팀, 계정플랫폼팀} 필수
  - 임시값: cause_confidence = 불명이거나 원인이 두 범주 이상에 걸치면 '잘 모르겠음'으로 보고 플랫폼운영팀으로 둔다. assignment_reason에 걸친 범주를 모두 적는다.
  - assignment_status ∈ {제안, 승인됨} 필수. 에이전트는 '제안'까지만 쓸 수 있다.
- 사람 확인: 승인 필요 (다른 팀의 일을 움직이는 단계)
- 근거: 원본 4절 "원인에 맞는 적절한 팀에 배정한다." 및 대응 목록, "잘 모르겠으면 플랫폼운영팀에 넣는다." / '잘 모르겠음'의 조건과 승인 주체는 열린 질문 Q5 답변 전 임시값

### 단계 7. 고객 공지 초안
- 할 일: 공지 대상 장애이면 고객 공지 초안을 쓰고 승인 대기로 올린다(발송은 하지 않는다).
- 산출물: notice_required, notice_draft, notice_status
- 산출물 조건:
  - notice_required ∈ {예, 아니오, 검토필요} 필수. 임시값: S1 → 예, S2 → 검토필요, S3 → 아니오
  - notice_required ∈ {예, 검토필요}이면 notice_draft 필수(빈 값 금지). 임시로 초안에는 영향 범위와 발생 시각을 넣고, cause_hypothesis·내부 팀명·배포 ID 같은 내부 추정 정보는 넣지 않는다.
  - notice_status ∈ {해당없음, 초안, 승인대기, 승인됨, 발송됨} 필수. 에이전트가 쓸 수 있는 값은 {해당없음, 초안, 승인대기}뿐이다.
  - notice_required = 아니오 → notice_status = 해당없음, notice_draft는 빈 값
- 사람 확인: 승인 필요 (대외 발송)
- 근거: 원본 5절 "심각한 장애는 고객 공지를 낸다." "공지 문구는 상황에 맞게 작성한다." / 공지 대상 심각도와 승인자는 열린 질문 Q6 답변 전 임시값, 초안 필수 항목은 Q7 답변 전 임시값

### 단계 8. 티켓 기록
- 할 일: 단계 1~7의 결과를 티켓에 처리 기록으로 남긴다.
- 산출물: ticket_note, open_question_refs
- 산출물 조건: ticket_note 필수. 임시로 severity, cause_category, cause_hypothesis, assigned_team, assignment_status, notice_status, escalation_needed를 모두 담아야 한다. open_question_refs는 이 티켓 처리에 쓴 임시값의 질문 번호 목록(Q1~Q9 부분집합, 없으면 빈 목록).
- 사람 확인: 없음
- 근거: 원본 6절 "처리 내용을 티켓에 적절히 남긴다." / 필수 항목은 열린 질문 Q8 답변 전 임시값

---

## 출력 형식

장애 1건의 분석 결과는 아래 필드를 모두 가져야 한다. '조건부 필수'는 조건에 맞을 때만 필수이고, 그렇지 않으면 null 또는 빈 값으로 둔다.

| 필드 | 타입 | 필수 | 허용 값 / 조건 |
|---|---|---|---|
| ticket_id | string | 필수 | 빈 값 금지 |
| received_at | string | 필수 | ISO 8601 일시 |
| ticket_summary | string | 필수 | 빈 값 금지 |
| logs_checked | boolean | 필수 | true, false |
| log_sources | list[string] | 조건부 필수 | logs_checked = true이면 1개 이상 |
| log_time_range | string | 조건부 필수 | logs_checked = true이면 "시작~끝"(ISO 8601), 티켓 발생 시각 포함 |
| error_summary | string | 필수 | 빈 값 금지(에러가 없으면 "에러 없음") |
| affected_scope | enum | 필수 | 전체_또는_다수, 일부, 거의_없음, 불명 |
| severity | enum | 필수 | S1, S2, S3 |
| severity_basis | string | 필수 | 빈 값 금지 |
| severity_needs_review | boolean | 필수 | true, false. affected_scope = 불명이면 true |
| escalation_needed | boolean | 필수 | true, false. severity_needs_review = true이면 true |
| escalation_reason | string | 조건부 필수 | escalation_needed = true이면 빈 값 금지 |
| severity_confirmed_by | string | 필수 | 확정자 식별자 또는 "미확정" |
| recent_deploy | enum | 필수 | yes, no, unknown |
| deploy_id | string | 조건부 필수 | recent_deploy = yes이면 빈 값 금지 |
| minutes_since_deploy | integer | 조건부 필수 | recent_deploy = yes이면 0 이상 정수 |
| cause_category | enum | 필수 | network, platform_app, billing, auth, unknown |
| cause_hypothesis | string | 필수 | 빈 값 금지 |
| cause_confidence | enum | 필수 | 확인됨, 추정, 불명 |
| assigned_team | enum | 필수 | 네트워크운영팀, 플랫폼운영팀, 빌링운영팀, 계정플랫폼팀. cause_category와 대응 규칙이 맞아야 함(unknown → 플랫폼운영팀) |
| assignment_status | enum | 필수 | 제안, 승인됨 (에이전트 출력은 제안만) |
| assignment_reason | string | 필수 | 빈 값 금지 |
| notice_required | enum | 필수 | 예, 아니오, 검토필요 (임시: S1→예, S2→검토필요, S3→아니오) |
| notice_draft | string | 조건부 필수 | notice_required ∈ {예, 검토필요}이면 빈 값 금지, 아니오이면 빈 값 |
| notice_status | enum | 필수 | 해당없음, 초안, 승인대기, 승인됨, 발송됨 (에이전트 출력은 해당없음·초안·승인대기만) |
| ticket_note | string | 필수 | severity·cause_category·cause_hypothesis·assigned_team·assignment_status·notice_status·escalation_needed 포함 |
| open_question_refs | list[string] | 필수 | Q1~Q9의 부분집합, 없으면 빈 목록 |

교차 검증 규칙
1. recent_deploy = yes이고 원인 근거가 배포뿐이면 cause_confidence ≠ 확인됨
2. cause_confidence = 불명이면 cause_category = unknown이고 assigned_team = 플랫폼운영팀
3. 에이전트가 낸 출력에는 assignment_status = 승인됨, notice_status ∈ {승인됨, 발송됨}이 나올 수 없다

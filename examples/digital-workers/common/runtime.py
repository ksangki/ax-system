"""실행 런타임 — 다섯 에이전트가 함께 쓰는 '거두는 체계'의 축소판.

에이전트 하나가 돌 때 여기서 네 가지가 일어난다.
  1. 등록부 확인   — 등록되지 않았거나 활성이 아니면 시작하지 않는다 (5장)
  2. 행위 허가     — 도구를 쓰기 직전에 등록부의 허용 수준을 다시 본다 (7장)
  3. 감사 로그     — 허가·거부·승인을 전부 logs/audit.jsonl에 남긴다 (5장 6번 칸)
  4. 비용 로그     — 토큰과 금액, 처리 건수를 logs/usage.jsonl에 남긴다 (6장·8장)

에이전트 코드 자체는 '무엇을 할 수 있는가'(도구)만 정의한다.
'무엇을 해도 되는가'는 등록부가 정하고, 이 파일이 그 둘을 맞대 본다.
"""
import datetime
import json
import pathlib
import sys
import uuid

import anthropic

from . import registry

MODEL = "claude-opus-5-5"

# 100만 토큰당 달러 (Claude Opus 5.5, 2026-10 기준 공개 가격).
# 캐시 쓰기는 입력 단가의 1.25배, 캐시 읽기는 0.05배다.
PRICE = {"input": 4.00, "output": 20.00, "cache_write": 5.00, "cache_read": 0.20}

ROOT = registry.ROOT
LOGS = ROOT / "logs"
OUTPUTS = ROOT / "outputs"


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _append(path: pathlib.Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


class Run:
    """에이전트 한 번의 실행. 도구 함수는 이 객체를 통해 허가를 받는다."""

    def __init__(self, agent_id: str, approve: str = "ask"):
        # approve: ask(터미널에서 묻는다) | yes(전부 승인) | no(전부 거절)
        self.entry = registry.entry(agent_id)
        self.agent_id = agent_id
        self.approve = approve
        self.run_id = f"{agent_id}-{datetime.date.today():%Y%m%d}-{uuid.uuid4().hex[:6]}"
        self.items = 0           # 처리 건수 — 8장 환산의 분자
        self.human_touches = 0   # 사람이 개입한 횟수(승인·넘김) — 8장 자율성 계수의 재료

        status = self.entry.get("status")
        if status != "active":
            self.audit("run_blocked", reason=f"등록부 상태가 {status}")
            sys.exit(f"[{agent_id}] 등록부 상태가 '{status}'라 실행하지 않습니다.")
        self.audit("run_start", aal=self.entry["review"]["aal"])

    # ── 감사 로그 ──────────────────────────────────────────────
    def audit(self, event: str, **detail) -> None:
        _append(LOGS / "audit.jsonl", {
            "time": _now(), "run_id": getattr(self, "run_id", None),
            "agent_id": self.agent_id, "event": event, **detail,
        })

    # ── 권한 범위(2번 칸): 어디까지 닿을 수 있는가 ───────────────────
    def check_read(self, path: str) -> pathlib.Path:
        target = (ROOT / path).resolve()
        allowed = [(ROOT / p).resolve() for p in self.entry["permissions"]["read"]]
        if not any(target == a or a in target.parents for a in allowed):
            self.audit("read_denied", path=path)
            raise PermissionError(f"등록부의 읽기 범위 밖입니다: {path}")
        self.audit("read", path=path)
        return target

    # ── 행위 범위(4번 칸): 무엇을 해도 되는가 ─────────────────────────
    def authorize(self, action: str, summary: str) -> tuple[bool, str]:
        """도구가 실제로 무언가를 하기 직전에 부른다.

        돌려주는 문장은 그대로 모델에게 도구 결과로 전달된다.
        거부된 경우에도 이유를 알려줘야 모델이 다른 길을 찾는다.
        """
        level = self.entry["actions"].get(action)
        if level is None:
            self.audit("action_denied", action=action, summary=summary)
            return False, f"거부됨: '{action}'은 등록부에 없는 행위입니다. 실행하지 않았습니다."
        if level == "suggest":
            self.audit("action_suggested", action=action, summary=summary)
            _append(OUTPUTS / "suggestions.jsonl", {
                "time": _now(), "agent_id": self.agent_id, "action": action, "summary": summary,
            })
            return False, (f"'{action}'은 제안만 허용됩니다. 실행하지 않고 사람이 볼 제안 목록에 "
                           "올렸습니다. 다른 일을 계속하세요.")
        if level == "approve":
            ok = self._ask_human(action, summary)
            self.human_touches += 1
            self.audit("action_approved" if ok else "action_rejected", action=action, summary=summary)
            if not ok:
                return False, f"담당자가 '{action}'을 승인하지 않았습니다. 실행하지 않았습니다."
            return True, "승인됨"
        self.audit("action_auto", action=action, summary=summary)
        return True, "허용됨"

    def _ask_human(self, action: str, summary: str) -> bool:
        if self.approve in ("yes", "no"):
            return self.approve == "yes"
        print(f"\n  ┌ 승인 요청 [{self.agent_id}] {action}\n  │ {summary}")
        answer = input("  └ 승인할까요? (y/N) ").strip().lower()
        return answer in ("y", "yes", "예", "ㅇ")

    def count(self, n: int = 1) -> None:
        self.items += n

    # ── 실행: SDK의 Tool Runner가 도구 호출 루프를 돌린다 ─────────────────
    def run(self, system: str, task: str, tools: list, effort: str = "medium") -> str:
        client = anthropic.Anthropic()  # ANTHROPIC_API_KEY 환경 변수를 읽는다
        runner = client.beta.messages.tool_runner(
            model=MODEL,
            max_tokens=16000,
            system=system,
            tools=tools,
            messages=[{"role": "user", "content": task}],
            output_config={"effort": effort},
            # 같은 시스템 프롬프트·도구 정의가 루프마다 반복되므로 캐시해 둔다 (6장: 청구서)
            cache_control={"type": "ephemeral"},
            # 안전 분류기가 거절하면 서버가 다른 모델로 이어서 처리한다
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )

        usage = {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0}
        final = None
        for message in runner:
            final = message
            u = message.usage
            usage["input"] += u.input_tokens or 0
            usage["output"] += u.output_tokens or 0
            usage["cache_write"] += u.cache_creation_input_tokens or 0
            usage["cache_read"] += u.cache_read_input_tokens or 0
            for block in message.content:
                if block.type == "tool_use":
                    print(f"  · {block.name}({_short(block.input)})")

        cost = sum(usage[k] * PRICE[k] for k in usage) / 1_000_000
        stop = final.stop_reason if final else None
        _append(LOGS / "usage.jsonl", {
            "time": _now(), "run_id": self.run_id, "agent_id": self.agent_id,
            "model": final.model if final else MODEL, "stop_reason": stop,
            "tokens": usage, "cost_usd": round(cost, 4),
            "items": self.items, "human_touches": self.human_touches,
        })
        self.audit("run_end", items=self.items, cost_usd=round(cost, 4), stop_reason=stop)
        print(f"\n  처리 {self.items}건 · 사람 개입 {self.human_touches}회 · "
              f"토큰 입력 {usage['input'] + usage['cache_read'] + usage['cache_write']:,} / "
              f"출력 {usage['output']:,} · 약 ${cost:.3f}")

        if final is None:
            return ""
        if stop == "refusal":
            return "(모델이 이 요청을 처리하지 않았습니다 — stop_reason: refusal)"
        return "\n".join(b.text for b in final.content if b.type == "text")


def _short(value, limit: int = 70) -> str:
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "…"


def write_output(name: str, text: str) -> pathlib.Path:
    OUTPUTS.mkdir(exist_ok=True)
    path = OUTPUTS / name
    path.write_text(text, encoding="utf-8")
    return path

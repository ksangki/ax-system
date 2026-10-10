"""등록부 — 5장의 여덟 칸을 코드가 읽는 파일(registry.yaml)로 둔 것.

에이전트는 실행할 때마다 여기서 자기 칸을 읽는다. 등록부에 없거나
활성 상태가 아니면 실행되지 않는다. 등록부가 문서가 아니라 스위치가 되는 자리다.
"""
import datetime
import pathlib

from ruamel.yaml import YAML  # 주석을 보존한 채 고쳐 쓰기 위해 PyYAML 대신 쓴다

ROOT = pathlib.Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "registry.yaml"

# 5장: 행위별 허용 수준 넷. 아래로 갈수록 사람 손이 덜 간다.
#   suggest — 제안만 하고 실행하지 않는다
#   read    — 읽기만 한다
#   approve — 사람이 건건이 승인해야 실행된다
#   auto    — 미리 정한 범위 안에서는 스스로 실행한다
LEVELS = ("suggest", "read", "approve", "auto")

_yaml = YAML()
_yaml.width = 100
_yaml.indent(mapping=2, sequence=2, offset=0)


def load() -> dict:
    with REGISTRY.open(encoding="utf-8") as f:
        return _yaml.load(f)


def save(data: dict) -> None:
    with REGISTRY.open("w", encoding="utf-8") as f:
        _yaml.dump(data, f)


def entry(agent_id: str) -> dict:
    for item in load()["agents"]:
        if item["identity"]["agent_id"] == agent_id:
            return item
    raise KeyError(f"등록부에 없는 에이전트: {agent_id}")


def update(agent_id: str, **fields) -> dict:
    """등록부의 한 에이전트 칸을 고친다. 폐기 점검 에이전트(⑤)만 쓴다."""
    data = load()
    for item in data["agents"]:
        if item["identity"]["agent_id"] == agent_id:
            for key, value in fields.items():
                item[key] = value
            save(data)
            return item
    raise KeyError(f"등록부에 없는 에이전트: {agent_id}")


def plain(value):
    """ruamel 객체를 json.dumps가 받는 기본 타입으로 바꾼다 (도구 결과용)."""
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    return value


def today() -> str:
    return datetime.date.today().isoformat()

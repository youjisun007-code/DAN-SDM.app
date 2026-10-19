# -*- coding: utf-8 -*-
"""Elwyn et al.(2012) 3단계 공동의사결정(SDM) 모델 + 김영정의 합리적 의사결정
9단계 도식 기반 자동 평가.

전체 워크플로우는 사례에 관계없이 공통이다:
- 1~5단계(사전 진단): 학생이 채팅 전에 문제/갈등 정의, 통제 가능·불가능 영역
  분류, 숨은 전제를 직접 작성한다.
- 6~8단계(SDM 대화): Choice Talk / Option Talk / Decision Talk를 실천하며
  AI 상대방과 채팅한다.
- 9단계(사후 성찰): 대화 종료 후 성찰문을 작성한다.

이 모듈은 대화 내용뿐 아니라 1단계 답변과 9단계 성찰문까지 종합해
Choice/Option/Decision Talk 3개 항목 + Ethical Reasoning(9단계 기반 통제
분리·성찰 수준) 1개 항목, 총 4개 항목에 대해 1~10점과 코멘트를 생성하고
전체 총평을 덧붙인다. 결과는 Google Sheets 웹훅으로 전송되어 연구자가
확인한다.
"""

import json
import re
import socket
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

import anthropic

SDM_FEEDBACK_SCHEMA = {
    "type": "object",
    "properties": {
        "choice_talk": {
            "type": "object",
            "properties": {
                "score": {"type": "integer", "enum": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]},
                "comment": {"type": "string"},
            },
            "required": ["score", "comment"],
            "additionalProperties": False,
        },
        "option_talk": {
            "type": "object",
            "properties": {
                "score": {"type": "integer", "enum": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]},
                "comment": {"type": "string"},
            },
            "required": ["score", "comment"],
            "additionalProperties": False,
        },
        "decision_talk": {
            "type": "object",
            "properties": {
                "score": {"type": "integer", "enum": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]},
                "comment": {"type": "string"},
            },
            "required": ["score", "comment"],
            "additionalProperties": False,
        },
        "ethical_reasoning": {
            "type": "object",
            "properties": {
                "score": {"type": "integer", "enum": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]},
                "comment": {"type": "string"},
            },
            "required": ["score", "comment"],
            "additionalProperties": False,
        },
        "overall_comment": {"type": "string"},
    },
    "required": [
        "choice_talk",
        "option_talk",
        "decision_talk",
        "ethical_reasoning",
        "overall_comment",
    ],
    "additionalProperties": False,
}

CATEGORY_LABELS = {
    "choice_talk": "Choice Talk (선택 인지)",
    "option_talk": "Option Talk (선택지 설명)",
    "decision_talk": "Decision Talk (결정 도출)",
    "ethical_reasoning": "Ethical Reasoning (윤리적 성찰)",
}


def build_evaluation_prompt(case, transcript, step3_reflection=""):
    return f"""다음은 예비 한의사(학생)와 '{case['chief_complaint']}' 상황의 {case['counterpart_role']} "
간의 공동의사결정(Shared Decision Making) 연습 자료 전체입니다. 김영정의 합리적 의사결정 9단계 도식에서
6~8단계(SDM 대화)는 실제 채팅으로, 9단계(사후 성찰)는 대화 종료 후에 학생이 직접 작성했습니다.

[이 사례의 핵심 윤리적 쟁점 — 채점 시 참고]
{case['ethical_issues']}

[6~8단계: 실제 SDM 대화 내용]
{transcript}

[9단계: 학생의 사후 성찰문 — "나의 대화가 상대방에게 미친 윤리적 영향과 나의 한계는 무엇이었는가?"]
{step3_reflection or '(작성하지 않음)'}

학생의 공동의사결정 역량과 윤리적 성찰 수준을 아래 4가지 항목으로 평가해주세요.

1. Choice Talk (선택 인지): 대화에서 여러 선택지가 존재함을 상대방에게 분명히 알리고, 성급한 결론을 피하며
   동등한 파트너십을 형성했는가.
2. Option Talk (선택지 설명): 각 선택지의 장단점·근거를 이해하기 쉽게 설명하고, 상대방의 이해를 확인했는가.
3. Decision Talk (결정 도출): 상대방의 가치와 선호를 이끌어내고, 이를 반영해 함께 결정(또는 신중한 유예)에
   도달했는가.
4. Ethical Reasoning (윤리적 성찰): 대화 중에 통제 가능한 영역(나의 설명·태도)과 통제할 수 없는 영역(상대의
   선택권, 법적 강제 불가 등)을 얼마나 현실적으로 구분해서 접근했는지, 그리고 9단계 성찰문에서 자신이
   상대방에게 미친 윤리적 영향과 스스로의 한계를 얼마나 깊이 있게 돌아보았는지를 평가한다. 성찰문을 작성하지
   않았다면 그 사실만 감점 요인으로 반영한다.

각 항목에 대해 1~10점 사이의 점수와 그렇게 평가한 이유를 한국어로 간결하게 작성하고, 전체적인 총평도
한국어로 2~4문장으로 작성해주세요. 총평에는 이 사례의 윤리적 쟁점을 학생이 대화와 사후 성찰 전반에 걸쳐
얼마나 균형 있게 다루었는지도 포함해주세요."""


PLAIN_JSON_INSTRUCTIONS = """

응답은 다른 말 없이 아래 형식의 JSON 객체 하나만 출력하세요 (마크다운 코드블록도 쓰지 마세요):
{
  "choice_talk": {"score": 1~10 사이 정수, "comment": "한국어 코멘트"},
  "option_talk": {"score": 1~10 사이 정수, "comment": "한국어 코멘트"},
  "decision_talk": {"score": 1~10 사이 정수, "comment": "한국어 코멘트"},
  "ethical_reasoning": {"score": 1~10 사이 정수, "comment": "한국어 코멘트"},
  "overall_comment": "한국어 총평"
}"""


def _extract_json_object(text):
    """모델이 JSON 앞뒤에 설명을 덧붙였을 때를 대비해, 첫 '{'부터 마지막 '}'까지만 골라 파싱한다."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _is_overloaded_error(err):
    return isinstance(err, anthropic.APIStatusError) and err.status_code in (503, 529)


# 다인원 동시 접속 시 429(rate limit)·5xx(일시적 서버 과부하)가 정상적으로 발생할
# 수 있으므로, 요청을 완전히 실패시키기 전에 짧은 지수 백오프로 재시도한다.
RETRYABLE_STATUS_CODES = (429, 500, 502, 503, 529)


def call_anthropic_with_retry(fn, max_retries=3, base_delay=1.0, max_delay=3.0):
    """fn()을 호출하고, 429/5xx 응답이나 연결 오류가 나면 최대 max_retries회까지
    1~3초 간격의 지수 백오프로 재시도한다. 그 외의 오류(인증 오류, 잘못된 요청 등)는
    재시도해도 성공할 가능성이 없으므로 즉시 그대로 올린다.
    """
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except anthropic.APIConnectionError as e:
            last_err = e
        except anthropic.APIStatusError as e:
            if e.status_code not in RETRYABLE_STATUS_CODES:
                raise
            last_err = e
        if attempt < max_retries:
            time.sleep(min(base_delay * (2 ** attempt), max_delay))
    raise last_err


def request_sdm_feedback(client, model, analysis_prompt, max_retries=3):
    """SDM 3단계 피드백을 요청한다.

    구조화 출력(json_schema)을 우선 시도하며, 429(rate limit)·5xx(일시적 과부하)
    응답이나 연결 오류에는 짧게 재시도한다. 그래도 계속 과부하(503/529,
    "Grammar compilation ...")라면, 형식 제약 없는 일반 텍스트 요청으로 자동
    전환해 같은 모양의 JSON을 받아낸다(이 대체 경로도 재시도를 적용한다).
    """

    def structured_call():
        response = client.messages.create(
            model=model,
            max_tokens=1600,
            output_config={
                "effort": "medium",
                "format": {"type": "json_schema", "schema": SDM_FEEDBACK_SCHEMA},
            },
            messages=[{"role": "user", "content": analysis_prompt}],
        )
        text = next(b.text for b in response.content if b.type == "text")
        return json.loads(text)

    try:
        return call_anthropic_with_retry(structured_call, max_retries=max_retries)
    except anthropic.APIStatusError as e:
        if not _is_overloaded_error(e):
            raise

        def plain_call():
            response = client.messages.create(
                model=model,
                max_tokens=1600,
                output_config={"effort": "medium"},
                messages=[{"role": "user", "content": analysis_prompt + PLAIN_JSON_INSTRUCTIONS}],
            )
            text = next(b.text for b in response.content if b.type == "text")
            return _extract_json_object(text)

        return call_anthropic_with_retry(plain_call, max_retries=2)


def describe_anthropic_error(err: Exception) -> str:
    if isinstance(err, TypeError) and "authentication" in str(err).lower():
        return "ANTHROPIC_API_KEY 환경 변수가 설정되어 있지 않습니다. .env 파일을 확인해주세요."
    if isinstance(err, anthropic.AuthenticationError):
        return "ANTHROPIC_API_KEY가 유효하지 않습니다."
    if isinstance(err, anthropic.RateLimitError):
        return "요청이 너무 많습니다. 잠시 후 다시 시도해주세요."
    if isinstance(err, anthropic.APIConnectionError):
        return "Claude API 서버에 연결할 수 없습니다. 네트워크를 확인해주세요."
    if isinstance(err, anthropic.APIStatusError):
        return f"Claude API 오류 ({err.status_code}): {err.message}"
    return f"알 수 없는 오류: {err}"


def categories_from_result(result):
    return [
        {
            "key": key,
            "title": CATEGORY_LABELS[key],
            "score": result[key]["score"],
            "comment": result[key]["comment"],
        }
        for key in ("choice_talk", "option_talk", "decision_talk", "ethical_reasoning")
    ]


def total_score_from_categories(categories):
    """4개 영역(각 10점) 점수를 합산한 총점(40점 만점)."""
    score_by_key = {c["key"]: c["score"] for c in categories}
    choice_score = score_by_key.get("choice_talk", 0)
    option_score = score_by_key.get("option_talk", 0)
    decision_score = score_by_key.get("decision_talk", 0)
    ethical_score = score_by_key.get("ethical_reasoning", 0)
    total_score = choice_score + option_score + decision_score + ethical_score
    return total_score


def log_session_to_sheet(
    webhook_url,
    webhook_token,
    student_id,
    student_name,
    case_label,
    history,
    categories,
    overall_comment,
    selected_principle="",
    step3_reflection="",
    on_error=None,
):
    """SDM 연습 대화 기록을 Google 스프레드시트 웹훅으로 전송 (설정 안 되어 있으면 조용히 건너뜀).

    selected_principle은 대화 시작 전 학생이 고른 윤리 원칙(성찰용, 정답 없음)을
    연구자가 참고할 수 있도록 함께 기록할 뿐, 채점에는 전혀 사용되지 않는다.
    step3_reflection은 대화 종료 후 9단계 사후 성찰문이다. categories의 각
    항목(choice_talk/option_talk/decision_talk/ethical_reasoning)은 점수뿐
    아니라 코멘트 전문도 함께 시트에 기록한다.
    """
    if not webhook_url:
        if on_error:
            on_error("GOOGLE_SHEETS_WEBHOOK_URL이 설정되지 않아 로그 전송을 건너뜁니다.")
        return

    transcript = "\n".join(
        f"{'학생' if turn.get('role') == 'student' else '환자/보호자'}: {turn.get('text', '')}"
        for turn in history
    )
    score_by_key = {c["key"]: c["score"] for c in categories}
    comment_by_key = {c["key"]: c["comment"] for c in categories}
    payload = {
        "token": webhook_token,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "student_id": student_id,
        "student_name": student_name,
        "case_label": case_label,
        "selected_principle": selected_principle,
        "turn_count": len([m for m in history if m.get("role") == "student"]),
        "choice_talk_score": score_by_key.get("choice_talk", ""),
        "choice_talk_comment": comment_by_key.get("choice_talk", ""),
        "option_talk_score": score_by_key.get("option_talk", ""),
        "option_talk_comment": comment_by_key.get("option_talk", ""),
        "decision_talk_score": score_by_key.get("decision_talk", ""),
        "decision_talk_comment": comment_by_key.get("decision_talk", ""),
        "ethical_reasoning_score": score_by_key.get("ethical_reasoning", ""),
        "ethical_reasoning_comment": comment_by_key.get("ethical_reasoning", ""),
        "total_score": total_score_from_categories(categories),
        "step3_reflection": step3_reflection,
        "overall_comment": overall_comment,
        "transcript": transcript,
    }
    # 다인원이 마지막에 몰려서 [피드백 받기]를 동시에 누르면 Apps Script 쪽이
    # 일시적으로 느려지거나(락 대기) 타임아웃될 수 있으므로 네트워크 오류에
    # 한해 두 번까지 짧게 재시도한다. 웹훅이 명시적으로 {"error": ...}를
    # 반환한 경우(토큰 불일치 등)는 재시도해도 소용없으므로 바로 실패 처리한다.
    last_network_err = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                webhook_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = resp.read().decode("utf-8", errors="replace")
            try:
                body_json = json.loads(body)
            except json.JSONDecodeError:
                body_json = None
            error_msg = body_json.get("error") if isinstance(body_json, dict) else None
            if error_msg:
                # Apps Script의 LockService가 바빠서 거절한 경우(동시 제출 몰림)는
                # 네트워크 오류와 마찬가지로 재시도할 가치가 있다. 그 외(잘못된
                # 토큰 등)는 재시도해도 소용없으므로 바로 실패 처리한다.
                if "busy" in str(error_msg).lower() and attempt < 2:
                    last_network_err = error_msg
                    time.sleep(1.0 * (attempt + 1))
                    continue
                if on_error:
                    on_error(f"웹훅이 오류를 반환했습니다: {error_msg}")
                return False
            return True
        except (urllib.error.URLError, urllib.error.HTTPError, socket.timeout, TimeoutError) as e:
            last_network_err = e
            if attempt < 2:
                time.sleep(1.0 * (attempt + 1))
                continue
    if on_error:
        on_error(last_network_err)
    return False

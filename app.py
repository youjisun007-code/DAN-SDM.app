import json
import os
import re

import anthropic
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, session, redirect, url_for

from cases import (
    CASES,
    DEFAULT_CASE_ID,
    ETHICS_PRINCIPLES,
    SDM_TOTAL_TURNS,
    SDM_EARLY_END_TURN,
    get_case,
    build_system_prompt,
)
from sdm_eval import (
    build_evaluation_prompt,
    describe_anthropic_error,
    categories_from_result,
    log_session_to_sheet,
    total_score_from_categories,
    request_sdm_feedback,
    call_anthropic_with_retry,
)

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment

MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5")
STUDENT_PASSWORD = os.environ.get("STUDENT_PASSWORD")
SHEETS_WEBHOOK_URL = os.environ.get("GOOGLE_SHEETS_WEBHOOK_URL")
SHEETS_WEBHOOK_TOKEN = os.environ.get("GOOGLE_SHEETS_WEBHOOK_TOKEN")

# static/css, static/js 변경 시 올려서 브라우저 캐시를 무효화한다.
ASSET_VERSION = "16"


@app.context_processor
def inject_asset_version():
    return {"asset_version": ASSET_VERSION}


@app.template_filter("sentences")
def split_sentences(text):
    """배경 상황 줄글을 가독성을 위해 줄바꿈/문장 단위(한국어 종결어미 + 마침표)로 나눈다."""
    parts = []
    for line in (text or "").splitlines():
        parts.extend(re.split(r"(?<=[다요죠까]\.)\s+", line.strip()))
    return [p for p in parts if p]


@app.before_request
def require_login():
    if not STUDENT_PASSWORD:
        return  # 비밀번호가 설정되지 않았으면 인증을 건너뜀 (로컬 개발용)
    if request.endpoint in ("login", "static"):
        return
    if not session.get("authenticated"):
        return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if request.form.get("password") == STUDENT_PASSWORD:
            session["authenticated"] = True
            return redirect(url_for("index"))
        error = "비밀번호가 올바르지 않습니다."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


def history_to_messages(history):
    """프론트엔드 history([{role: 'student'|'counterpart', text}]) 를 Claude 메시지 형식으로 변환."""
    messages = []
    for turn in history:
        role = "user" if turn.get("role") == "student" else "assistant"
        text = (turn.get("text") or "").strip()
        if text:
            messages.append({"role": role, "content": text})
    return messages


@app.route("/")
def index():
    requested_id = request.args.get("case")
    if requested_id in CASES:
        session["case_id"] = requested_id
    case_id = session.get("case_id", DEFAULT_CASE_ID)
    if case_id not in CASES:
        case_id = DEFAULT_CASE_ID
    session["case_id"] = case_id

    case = get_case(case_id)
    case_list = [
        {"id": cid, "label": c["label"], "difficulty": c["difficulty"]}
        for cid, c in CASES.items()
    ]
    return render_template(
        "index.html",
        case=case,
        case_id=case_id,
        case_list=case_list,
        ethics_principles=ETHICS_PRINCIPLES,
        sdm_total_turns=SDM_TOTAL_TURNS,
        sdm_early_end_turn=SDM_EARLY_END_TURN,
    )


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    history = data.get("history", [])

    if not message:
        return jsonify({"error": "메시지가 비어 있습니다."}), 400

    case = get_case(session.get("case_id", DEFAULT_CASE_ID))
    claude_messages = history_to_messages(history)
    claude_messages.append({"role": "user", "content": message})

    # 이번 메시지가 전체 상담 중 몇 번째 학생 발화인지 계산해 SDM 3단계(Choice/
    # Option/Decision Talk) 턴 가이드를 시스템 프롬프트에 반영한다.
    turn_number = len([m for m in history if m.get("role") == "student"]) + 1

    def call():
        return client.messages.create(
            model=MODEL,
            max_tokens=400,
            system=build_system_prompt(case, turn_number=turn_number),
            output_config={"effort": "low"},
            messages=claude_messages,
        )

    try:
        response = call_anthropic_with_retry(call, max_retries=3)
        reply = next((b.text for b in response.content if b.type == "text"), "...")
    except (anthropic.APIError, TypeError) as e:
        reply = f"(응답 오류: {describe_anthropic_error(e)})"

    return jsonify({"reply": reply})


@app.route("/api/feedback", methods=["POST"])
def feedback():
    data = request.get_json(silent=True) or {}
    history = data.get("history", [])
    student_id = (data.get("student_id") or "").strip() or "(학번 미입력)"
    student_name = (data.get("student_name") or "").strip() or "(이름 미입력)"
    turn_count = len([m for m in history if m.get("role") == "student"])

    principle_id = data.get("selected_principle")
    principle_label = next(
        (p["title"] for p in ETHICS_PRINCIPLES if p["id"] == principle_id), ""
    )

    # 김영정 9단계 도식 중 9단계: 대화 종료 후 작성하는 사후 성찰문
    step3_reflection = (data.get("step3_reflection") or "").strip()

    if not history:
        return jsonify({"error": "대화 내용이 없습니다."}), 400

    case = get_case(session.get("case_id", DEFAULT_CASE_ID))

    transcript = "\n".join(
        f"{'학생' if turn.get('role') == 'student' else '환자/보호자'}: {turn.get('text', '')}"
        for turn in history
    )

    analysis_prompt = build_evaluation_prompt(case, transcript, step3_reflection=step3_reflection)

    try:
        result = request_sdm_feedback(client, MODEL, analysis_prompt)
    except (anthropic.APIError, TypeError) as e:
        return jsonify(
            {
                "turn_count": turn_count,
                "categories": [],
                "overall_comment": f"피드백 생성 중 오류가 발생했습니다: {describe_anthropic_error(e)}",
                "options": [],
            }
        )
    except (json.JSONDecodeError, StopIteration) as e:
        return jsonify(
            {
                "turn_count": turn_count,
                "categories": [],
                "overall_comment": f"피드백 응답을 해석하지 못했습니다: {e}",
                "options": [],
            }
        )

    try:
        categories = categories_from_result(result)
        total_score = total_score_from_categories(categories)
        overall_comment = result["overall_comment"]
    except (KeyError, TypeError) as e:
        app.logger.warning("피드백 응답 형식이 예상과 달랐습니다: %s / result=%r", e, result)
        return jsonify(
            {
                "turn_count": turn_count,
                "categories": [],
                "overall_comment": "피드백 응답 형식이 올바르지 않아 채점 결과를 표시할 수 없습니다. 다시 시도해주세요.",
                "options": [],
            }
        )

    logged_to_sheet = False
    try:
        logged_to_sheet = log_session_to_sheet(
            SHEETS_WEBHOOK_URL,
            SHEETS_WEBHOOK_TOKEN,
            student_id,
            student_name,
            case["label"],
            history,
            categories,
            overall_comment,
            selected_principle=principle_label,
            step3_reflection=step3_reflection,
            on_error=lambda e: app.logger.warning("Google Sheets 로그 전송 실패: %s", e),
        )
    except Exception as e:
        # 시트 로깅은 부가 기능이므로, 여기서 어떤 예외가 나더라도 학생에게 보여줄
        # 피드백 결과 자체는 절대 막지 않는다.
        app.logger.warning("Google Sheets 로그 전송 중 예상치 못한 오류: %s", e)

    return jsonify(
        {
            "turn_count": turn_count,
            "categories": categories,
            "total_score": total_score,
            "overall_comment": overall_comment,
            "options": case.get("options", []),
            "logged_to_sheet": bool(logged_to_sheet),
            # 시트 전송이 실패했을 때 프론트엔드가 localStorage에 백업해뒀다가
            # /api/resync-sheet로 재전송을 시도할 수 있도록 필요한 값을 함께 내려준다.
            "case_label": case["label"],
            "selected_principle_label": principle_label,
        }
    )


@app.route("/api/resync-sheet", methods=["POST"])
def resync_sheet():
    """네트워크 문제 등으로 Google Sheets 기록에 실패했던 피드백 결과를
    프론트엔드가 localStorage에서 다시 보내 재시도하는 엔드포인트.
    이미 계산된 점수·코멘트를 그대로 쓸 뿐, Claude를 다시 호출하지 않는다.
    """
    data = request.get_json(silent=True) or {}
    student_id = (data.get("student_id") or "").strip() or "(학번 미입력)"
    student_name = (data.get("student_name") or "").strip() or "(이름 미입력)"
    case_label = (data.get("case_label") or "").strip()
    history = data.get("history", [])
    categories = data.get("categories", [])
    overall_comment = data.get("overall_comment", "")
    principle_label = (data.get("selected_principle_label") or "").strip()
    step3_reflection = (data.get("step3_reflection") or "").strip()

    if not case_label or not categories:
        return jsonify({"logged_to_sheet": False, "error": "재전송에 필요한 데이터가 부족합니다."}), 400

    logged_to_sheet = False
    try:
        logged_to_sheet = log_session_to_sheet(
            SHEETS_WEBHOOK_URL,
            SHEETS_WEBHOOK_TOKEN,
            student_id,
            student_name,
            case_label,
            history,
            categories,
            overall_comment,
            selected_principle=principle_label,
            step3_reflection=step3_reflection,
            on_error=lambda e: app.logger.warning("Google Sheets 재전송 실패: %s", e),
        )
    except Exception as e:
        app.logger.warning("Google Sheets 재전송 중 예상치 못한 오류: %s", e)

    return jsonify({"logged_to_sheet": bool(logged_to_sheet)})


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "true").lower() == "true"
    app.run(debug=debug, port=int(os.environ.get("PORT", 5000)))

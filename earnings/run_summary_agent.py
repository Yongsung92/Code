"""
earnings_calendar.csv 를 보고 아직 전문/요약이 없는 기업에 대해 Claude API(웹검색+웹읽기
서버 도구)를 직접 호출해, 실적 콜 전문을 정리해 로컬에만 저장하고(transcripts/, git에
올라가지 않음) 원본 한국어 요약을 작성한다(summary/, 다음 git 커밋으로 공개 대시보드에 올라감).

Claude Code 전체를 무인으로 돌리는 대신(자율적으로 파일시스템/Bash에 접근하는 에이전트를
새로 만드는 건 더 큰 권한이 필요해서) Claude API를 "검색 -> 날짜 검증 -> 요약" 한 번의
호출로만 쓴다 - 지금 있는 다른 배치들처럼 고정된 입출력을 가진 스크립트에 가깝다.

필요: ANTHROPIC_API_KEY 환경변수 (또는 `ant auth login`으로 저장된 프로필).
"""
import csv
import datetime
import json
import os
import sys

EARNINGS_DIR = os.path.dirname(os.path.abspath(__file__))
CALENDAR_PATH = os.path.join(EARNINGS_DIR, "earnings_calendar.csv")
TRANSCRIPTS_DIR = os.path.join(EARNINGS_DIR, "transcripts")
SUMMARY_DIR = os.path.join(EARNINGS_DIR, "summary")
MODEL = "claude-opus-5"

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "found": {"type": "boolean"},
        "date_verified": {"type": "boolean"},
        "source_url": {"type": "string"},
        "transcript": {"type": "string"},
        "summary": {"type": "string"},
        "note": {"type": "string"},
    },
    "required": ["found", "date_verified", "source_url", "transcript", "summary", "note"],
    "additionalProperties": False,
}

PROMPT_TEMPLATE = """{company}({ticker})의 {report_date}(또는 그 날짜가 포함된 분기) 실적 콜(어닝콜)
전문을 웹에서 찾아라 (예: "{company} earnings call transcript" 검색 - Investing.com,
Motley Fool 등에 흔히 게재됨).

중요 - 날짜 검증: 같은 회사의 다른 분기 전문과 섞이지 않도록, 페이지에 적힌 실적발표일/분기가
{report_date} 와 실제로 일치하는지 반드시 확인한 다음에만 사용해라. 확인이 안 되면
found/date_verified를 false로 하고 note에 이유를 적어라 - 틀린 분기를 쓰는 것보다 못 찾은 게 낫다.

찾았고 날짜가 확인되면:
1. transcript: 광고/네비게이션/관련기사 추천 등 페이지 잡다한 요소는 걷어내고 실제 실적 콜
   본문(모두발언 + Q&A)만, 발언자 이름을 구분해서("CEO 이름:", "애널리스트 이름 (소속):")
   정리해라. 문장 자체는 원문 그대로 - 요약하거나 바꿔 쓰지 않는다.
2. summary: 그 내용을 직접 읽고 이해한 뒤 아래 형식의 원본 한국어 요약을 새로 작성해라
   (번역이나 원문 복붙이 아니라 직접 재구성 - 이 필드는 공개 대시보드에 그대로 올라간다):
   - "주제 N:" 같은 라벨 없이 "1. ...", "2. ..." 식으로 번호만 붙인다.
   - 주제 개수는 고정하지 않고 내용에 맞게 자유롭게 정한다.
   - 각 주제는 5줄 이내로 요약한다.

source_url에는 실제로 사용한 페이지 URL을 적어라. found가 false면 transcript/summary는
빈 문자열로 두고 source_url도 빈 문자열로 둬도 된다."""


def load_calendar() -> list:
    with open(CALENDAR_PATH, encoding="utf-8-sig") as f:
        return [r for r in csv.DictReader(f) if r.get("ticker")]


def needs_work(ticker: str, report_date: str) -> tuple:
    if not report_date:
        return (False, False)
    has_transcript = os.path.exists(os.path.join(TRANSCRIPTS_DIR, f"{ticker}_{report_date}.txt"))
    has_summary = os.path.exists(os.path.join(SUMMARY_DIR, f"{ticker}_{report_date}.txt"))
    return (not has_transcript, not has_summary)


def process_one(client, ticker: str, company: str, report_date: str) -> str:
    """하나의 기업/분기를 처리한다. 결과 상태 문자열을 반환한다."""
    import anthropic

    prompt = PROMPT_TEMPLATE.format(company=company, ticker=ticker, report_date=report_date)
    messages = [{"role": "user", "content": prompt}]
    tools = [
        {"type": "web_search_20260209", "name": "web_search"},
        {"type": "web_fetch_20260209", "name": "web_fetch"},
    ]

    restarts = 0
    response = None
    while restarts < 5:
        with client.messages.stream(
            model=MODEL,
            max_tokens=32000,
            tools=tools,
            output_config={"effort": "high", "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
            messages=messages,
        ) as stream:
            response = stream.get_final_message()

        if response.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": response.content})
            restarts += 1
            continue
        break

    if response is None or response.stop_reason == "refusal":
        return f"[{ticker}] 응답 거부/실패"

    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        return f"[{ticker}] 텍스트 응답 없음 (stop_reason={response.stop_reason})"

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return f"[{ticker}] JSON 파싱 실패"

    if not data.get("found") or not data.get("date_verified"):
        return f"[{ticker}] 못 찾음/날짜 미확인: {data.get('note', '')}"

    wrote = []
    transcript = data.get("transcript", "").strip()
    if transcript:
        os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)
        path = os.path.join(TRANSCRIPTS_DIR, f"{ticker}_{report_date}.txt")
        if not os.path.exists(path):
            header = f"출처: {data.get('source_url', '')}\n수집일: {datetime.date.today().isoformat()}\n\n"
            with open(path, "w", encoding="utf-8") as f:
                f.write(header + transcript)
            wrote.append("transcript")

    summary = data.get("summary", "").strip()
    if summary:
        os.makedirs(SUMMARY_DIR, exist_ok=True)
        path = os.path.join(SUMMARY_DIR, f"{ticker}_{report_date}.txt")
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write(summary)
            wrote.append("summary")

    if not wrote:
        return f"[{ticker}] 변경 없음"
    return f"[{ticker}] 저장: {', '.join(wrote)}"


def main() -> bool:
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print("ANTHROPIC_API_KEY 환경변수가 없습니다. console.anthropic.com에서 발급해 설정하세요.")
        return False

    client = anthropic.Anthropic()

    rows = load_calendar()
    targets = []
    for row in rows:
        ticker = row["ticker"].strip()
        company = row["company"].strip()
        report_date = row.get("last_report_date", "").strip()
        need_t, need_s = needs_work(ticker, report_date)
        if need_t or need_s:
            targets.append((ticker, company, report_date))

    if not targets:
        print("처리할 기업 없음")
        return True

    ok = True
    for ticker, company, report_date in targets:
        try:
            result = process_one(client, ticker, company, report_date)
        except Exception as e:
            result = f"[{ticker}] 오류: {e}"
            ok = False
        print(result)

    return ok


if __name__ == "__main__":
    sys.exit(0 if main() else 1)

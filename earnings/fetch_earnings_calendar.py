"""
companies.csv에 등록된 기업들의 실적발표일을 가져와 earnings_calendar.csv로 저장한다.

날짜 자체는 사실관계(저작권 없음)라 Nasdaq의 공개 종목정보 API(로그인 불필요)를
그대로 쓴다. 이 API가 알려주는 건 "다음 실적발표일" 하나뿐이라, 그 날짜가 지나가는
순간을 감지해서 "지난 실적발표일(last_report_date)"로 옮겨 기록한다 - 대시보드가
summary/<ticker>_<last_report_date>.txt 를 찾아 보여주는 데 쓰는 키가 된다.

이 스크립트는 날짜만 다룬다. 실적 콜 "전문"은 저작권 있는 콘텐츠라 이 배치에서
자동 수집·게시하지 않는다 - 발표가 실제로 끝난 뒤 사람이 직접(또는 예약된
Claude Code 세션이) 전문을 참고해 원본 요약을 작성해 summary/ 폴더에 올린다.
"""
import csv
import json
import os
import sys
from datetime import datetime, date

EARNINGS_DIR = os.path.dirname(os.path.abspath(__file__))
COMPANIES_PATH = os.path.join(EARNINGS_DIR, "companies.csv")
CALENDAR_PATH = os.path.join(EARNINGS_DIR, "earnings_calendar.csv")
SUMMARY_DIR = os.path.join(EARNINGS_DIR, "summary")
STATE_PATH = os.path.join(EARNINGS_DIR, ".last_known_dates.json")

NASDAQ_URL = "https://api.nasdaq.com/api/quote/{ticker}/info?assetclass=stocks"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
}


def load_companies() -> list:
    with open(COMPANIES_PATH, encoding="utf-8-sig") as f:
        return [r for r in csv.DictReader(f) if r.get("ticker")]


def fetch_one(ticker: str) -> str:
    """해당 티커의 "다음 실적발표일"을 YYYY-MM-DD로 반환한다. 못 찾으면 빈 문자열."""
    import requests

    resp = requests.get(NASDAQ_URL.format(ticker=ticker), headers=HEADERS, timeout=20)
    resp.raise_for_status()
    data = resp.json().get("data") or {}
    for note in data.get("notifications") or []:
        for event in note.get("eventTypes") or []:
            if event.get("eventName") == "Earnings Date":
                # "Earnings Date : Nov 3, 2026" 형태의 문자열에서 날짜만 뽑는다.
                msg = event.get("message", "")
                raw = msg.split(":", 1)[-1].strip()
                try:
                    return datetime.strptime(raw, "%b %d, %Y").date().isoformat()
                except ValueError:
                    return ""
    return ""


def load_state() -> dict:
    if not os.path.exists(STATE_PATH):
        return {}
    with open(STATE_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_state(state: dict) -> None:
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def summary_exists(ticker: str, report_date: str) -> bool:
    if not report_date:
        return False
    return os.path.exists(os.path.join(SUMMARY_DIR, f"{ticker}_{report_date}.txt"))


def main() -> bool:
    companies = load_companies()
    state = load_state()
    today = date.today().isoformat()

    rows = []
    needs_summary = []  # 실적발표는 끝났는데 아직 summary/ 에 파일이 없는 것들
    for row in companies:
        ticker = row["ticker"].strip()
        company = row["company"].strip()
        prev = state.get(ticker, {})
        prev_next = prev.get("next_date", "")
        last_report_date = prev.get("last_report_date", "")

        try:
            next_date = fetch_one(ticker)
        except Exception as e:
            print(f"[{ticker}] 조회 실패: {e}")
            next_date = prev_next

        # 직전까지 "다음 실적일"로 잡아뒀던 날짜가 이제 과거가 됐다면,
        # 그게 곧 가장 최근 실적발표일이다.
        if prev_next and prev_next <= today and prev_next != last_report_date:
            last_report_date = prev_next

        state[ticker] = {"next_date": next_date, "last_report_date": last_report_date}
        rows.append({
            "ticker": ticker,
            "company": company,
            "next_earnings_date": next_date,
            "last_report_date": last_report_date,
            "updated_at": today,
        })

        if last_report_date and not summary_exists(ticker, last_report_date):
            needs_summary.append((ticker, company, last_report_date))

    with open(CALENDAR_PATH, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["ticker", "company", "next_earnings_date", "last_report_date", "updated_at"])
        writer.writeheader()
        writer.writerows(rows)

    save_state(state)

    print(f"{len(rows)}개 기업 실적일 갱신 -> {CALENDAR_PATH}")
    if needs_summary:
        print("다음 기업들은 실적발표가 지나갔지만 아직 요약이 없습니다:")
        for ticker, company, d in needs_summary:
            print(f"  - {company}({ticker}): {d}")
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)

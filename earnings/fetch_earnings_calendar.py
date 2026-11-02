"""
companies.csv에 등록된 기업들의 실적발표일을 가져와 earnings_calendar.csv로 저장한다.

날짜 자체는 사실관계(저작권 없음)라 Nasdaq의 공개 API(로그인 불필요)를 그대로 쓴다.
두 개의 다른 API를 합쳐서 쓰는데, 성격이 달라서다:
  - "다음 발표일"(next_earnings_date)은 /api/quote/{ticker}/info 의 notifications에
    Nasdaq이 날짜를 확정해 공지했을 때만 나타난다 - 회사가 아직 정식으로 날짜를 발표하지
    않았으면 이 API에도 없다. 이 경우 빈 칸("미정")이 맞는 상태다.
  - "이전 발표일"(last_report_date)은 /api/company/{ticker}/earnings-surprise 의
    earningsSurpriseTable 첫 행(dateReported)에서 바로 가져온다. 이미 지나간 실적이라
    공지 여부와 상관없이 항상 확정된 값으로 나온다 - next_earnings_date가 비어 있던
    티커도(아직 다음 날짜가 안 잡혀 있어도) last_report_date는 바로 채워진다.

이 스크립트는 날짜만 다룬다. 실적 콜 "전문"은 저작권 있는 콘텐츠라 이 배치에서
자동 수집·게시하지 않는다 - 발표가 실제로 끝난 뒤 사람이 직접(또는 예약된
Claude Code 세션이) 전문을 참고해 원본 요약을 작성해 summary/ 폴더에 올린다.
"""
import csv
import os
import sys
from datetime import datetime, date

EARNINGS_DIR = os.path.dirname(os.path.abspath(__file__))
COMPANIES_PATH = os.path.join(EARNINGS_DIR, "companies.csv")
CALENDAR_PATH = os.path.join(EARNINGS_DIR, "earnings_calendar.csv")
SUMMARY_DIR = os.path.join(EARNINGS_DIR, "summary")

NASDAQ_INFO_URL = "https://api.nasdaq.com/api/quote/{ticker}/info?assetclass=stocks"
NASDAQ_SURPRISE_URL = "https://api.nasdaq.com/api/company/{ticker}/earnings-surprise"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
}


def load_companies() -> list:
    with open(COMPANIES_PATH, encoding="utf-8-sig") as f:
        return [r for r in csv.DictReader(f) if r.get("ticker")]


def fetch_next_date(ticker: str) -> str:
    """"다음 실적발표일"을 YYYY-MM-DD로 반환한다. Nasdaq이 아직 공지하지 않았으면 빈 문자열."""
    import requests

    resp = requests.get(NASDAQ_INFO_URL.format(ticker=ticker), headers=HEADERS, timeout=20)
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


def fetch_last_report_date(ticker: str) -> str:
    """가장 최근(이미 끝난) 실적발표일을 YYYY-MM-DD로 반환한다. earnings-surprise 표의
    첫 행이 가장 최신 분기다. 데이터가 없으면 빈 문자열."""
    import requests

    resp = requests.get(NASDAQ_SURPRISE_URL.format(ticker=ticker), headers=HEADERS, timeout=20)
    resp.raise_for_status()
    rows = (resp.json().get("data") or {}).get("earningsSurpriseTable", {}).get("rows") or []
    if not rows:
        return ""
    raw = rows[0].get("dateReported", "")
    try:
        return datetime.strptime(raw, "%m/%d/%Y").date().isoformat()
    except ValueError:
        return ""


def summary_exists(ticker: str, report_date: str) -> bool:
    if not report_date:
        return False
    return os.path.exists(os.path.join(SUMMARY_DIR, f"{ticker}_{report_date}.txt"))


def main() -> bool:
    companies = load_companies()
    today = date.today().isoformat()

    rows = []
    needs_summary = []  # 실적발표는 끝났는데 아직 summary/ 에 파일이 없는 것들
    for row in companies:
        ticker = row["ticker"].strip()
        company = row["company"].strip()

        try:
            next_date = fetch_next_date(ticker)
        except Exception as e:
            print(f"[{ticker}] 다음 발표일 조회 실패: {e}")
            next_date = ""

        try:
            last_report_date = fetch_last_report_date(ticker)
        except Exception as e:
            print(f"[{ticker}] 이전 발표일 조회 실패: {e}")
            last_report_date = ""

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

    print(f"{len(rows)}개 기업 실적일 갱신 -> {CALENDAR_PATH}")
    if needs_summary:
        print("다음 기업들은 실적발표가 지나갔지만 아직 요약이 없습니다:")
        for ticker, company, d in needs_summary:
            print(f"  - {company}({ticker}): {d}")
    return True


if __name__ == "__main__":
    sys.exit(0 if main() else 1)

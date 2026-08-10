import requests
from bs4 import BeautifulSoup
import datetime
import csv
import os

HEADERS = {"User-Agent": "Mozilla/5.0"}


def get_investor_trend():
    today = datetime.datetime.now().strftime("%Y%m%d")
    url = f"https://finance.naver.com/sise/investorDealTrendDay.naver?bizdate={today}"
    res = requests.get(url, headers=HEADERS, timeout=10)
    res.encoding = "euc-kr"
    soup = BeautifulSoup(res.text, "html.parser")

    date_cell = soup.find("td", class_="date2")
    row = date_cell.find_parent("tr")
    cells = [td.get_text(strip=True) for td in row.find_all("td")]

    return {
        "날짜": cells[0],
        "개인": cells[1],
        "외국인": cells[2],
        "기관계": cells[3],
    }


def get_deal_rank(investor_gubun):
    url = (
        "https://finance.naver.com/sise/sise_deal_rank_iframe.naver"
        f"?sosok=01&investor_gubun={investor_gubun}&type=buy"
    )
    res = requests.get(url, headers=HEADERS, timeout=10)
    res.encoding = "euc-kr"
    soup = BeautifulSoup(res.text, "html.parser")

    results = []
    for tr in soup.select("table.type_1 tr"):
        tds = tr.find_all("td")
        link = tr.find("a")
        if len(tds) == 4 and link:
            name = link.get_text(strip=True)
            qty, amount, volume = [td.get_text(strip=True) for td in tds[1:]]
            results.append(
                {"종목명": name, "수량(천주)": qty, "금액(백만원)": amount, "당일거래량": volume}
            )
    return results


def save_to_csv(now, trend, foreign_top, inst_top):
    trend_path = "investor_trend.csv"
    write_header = not os.path.exists(trend_path)
    with open(trend_path, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["수집시각", "날짜", "개인", "외국인", "기관계"])
        writer.writerow([now, trend["날짜"], trend["개인"], trend["외국인"], trend["기관계"]])

    rank_path = "deal_rank.csv"
    write_header = not os.path.exists(rank_path)
    with open(rank_path, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(
                ["수집시각", "구분", "순위", "종목명", "수량(천주)", "금액(백만원)", "당일거래량"]
            )
        for i, r in enumerate(foreign_top, 1):
            writer.writerow(
                [now, "외국인", i, r["종목명"], r["수량(천주)"], r["금액(백만원)"], r["당일거래량"]]
            )
        for i, r in enumerate(inst_top, 1):
            writer.writerow(
                [now, "기관", i, r["종목명"], r["수량(천주)"], r["금액(백만원)"], r["당일거래량"]]
            )


def main():
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    trend = get_investor_trend()
    foreign_top = get_deal_rank(9000)
    inst_top = get_deal_rank(1000)

    print(f"[{now}] 투자자 동향: {trend}")
    print("외국인 순매수 상위:")
    for r in foreign_top[:5]:
        print(" ", r)
    print("기관 순매수 상위:")
    for r in inst_top[:5]:
        print(" ", r)

    save_to_csv(now, trend, foreign_top, inst_top)


if __name__ == "__main__":
    main()

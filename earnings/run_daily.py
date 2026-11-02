"""
매일 fetch_earnings_calendar.py 로 추적 중인 기업들의 다음 실적발표일을 갱신하고,
끝나면 sync_to_server.py 로 결과를 Lightsail 공개 대시보드(실적 탭)에 올리는
배치 진입점. 실적 콜 "전문" 수집·요약은 이 배치가 아니라 별도(사람 또는 예약된
Claude Code 세션)가 담당한다 - fetch_earnings_calendar.py 참고.

실행 로그는 earnings/run_daily.log 에 누적된다.
"""
import datetime
import os
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(BASE_DIR, "run_daily.log")
LAST_SUCCESS_PATH = os.path.join(BASE_DIR, ".last_success_date.txt")
SCRIPTS = ["fetch_earnings_calendar.py"]


def log(msg: str) -> None:
    line = f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    try:
        print(line)
    except Exception:
        pass
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run_script(name: str) -> bool:
    log(f"=== {name} 시작 ===")
    child_env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run(
        [sys.executable, name],
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=child_env,
    )
    if result.stdout:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(result.stdout)
    if result.returncode != 0:
        log(f"=== {name} 실패 (exit {result.returncode}) ===")
        if result.stderr:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(result.stderr)
        return False
    log(f"=== {name} 완료 ===")
    return True


def already_succeeded_today() -> bool:
    if not os.path.exists(LAST_SUCCESS_PATH):
        return False
    with open(LAST_SUCCESS_PATH, "r", encoding="utf-8") as f:
        return f.read().strip() == datetime.date.today().isoformat()


def mark_success_today() -> None:
    with open(LAST_SUCCESS_PATH, "w", encoding="utf-8") as f:
        f.write(datetime.date.today().isoformat())


def main():
    if already_succeeded_today():
        log("오늘 이미 성공적으로 완료되어 건너뜁니다.")
        return

    log("일일 배치 시작")
    ok = True
    for script in SCRIPTS:
        if not run_script(script):
            ok = False

    if not run_script("sync_to_server.py"):
        ok = False

    log("일일 배치 종료" + ("" if ok else " (일부 실패)"))
    if ok:
        mark_success_today()


if __name__ == "__main__":
    main()

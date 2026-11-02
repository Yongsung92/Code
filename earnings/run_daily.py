"""
매일 git pull로 클라우드 요약 에이전트가 올린 새 요약을 받아오고,
fetch_earnings_calendar.py 로 추적 중인 기업들의 다음 실적발표일을 갱신해 GitHub에
다시 push한 뒤(클라우드 루틴이 최신 "요약 필요" 목록을 보도록), sync_to_server.py 로
결과를 Lightsail 공개 대시보드(실적 탭)에 올리는 배치 진입점.

실적 콜 "전문" 수집·요약 자체는 이 PC가 아니라 GitHub(Yongsung92/Code)에 연결된
클라우드 Claude Code 루틴이 담당한다 - SSH 키는 이 로컬 PC에만 있고 클라우드에는
절대 올리지 않으므로, 클라우드 쪽은 summary/*.txt 를 git commit/push만 하고
이 배치가 그걸 pull 받아서 Lightsail로 올리는 역할을 나눠 맡는다.

실행 로그는 earnings/run_daily.log 에 누적된다.
"""
import datetime
import os
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CODE_DIR = os.path.dirname(BASE_DIR)
LOG_PATH = os.path.join(BASE_DIR, "run_daily.log")
LAST_SUCCESS_PATH = os.path.join(BASE_DIR, ".last_success_date.txt")
SCRIPTS = ["fetch_earnings_calendar.py"]
# pythonw.exe(콘솔 없음)가 git(콘솔 앱)을 띄우면 윈도우가 새 콘솔 창을 만들어 버린다 -
# 배치가 조용히 돌도록 창을 띄우지 않는다.
CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def git_pull() -> None:
    """클라우드 루틴이 push한 새 요약 파일을 받아온다. 실패해도 배치 전체를 막지는 않는다
    (네트워크가 없거나 GitHub 연동 전이어도 날짜 갱신·업로드는 계속 돌아가야 한다)."""
    try:
        result = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=CODE_DIR,
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=CREATE_NO_WINDOW,
        )
        if result.returncode == 0:
            log(f"git pull 완료: {result.stdout.strip() or '변경 없음'}")
        else:
            log(f"git pull 실패(무시하고 계속함): {result.stderr.strip()}")
    except Exception as e:
        log(f"git pull 중 오류(무시하고 계속함): {e}")


def git_push_calendar() -> None:
    """갱신된 earnings_calendar.csv를 GitHub에 올려서, 클라우드 요약 루틴이 최신
    '요약 필요' 목록을 보게 한다. 바뀐 게 없으면 조용히 넘어간다."""
    try:
        subprocess.run(
            ["git", "add", "earnings/earnings_calendar.csv"],
            cwd=CODE_DIR, capture_output=True, text=True, timeout=30, creationflags=CREATE_NO_WINDOW,
        )
        diff = subprocess.run(
            ["git", "diff", "--cached", "--quiet", "--", "earnings/earnings_calendar.csv"],
            cwd=CODE_DIR, timeout=30, creationflags=CREATE_NO_WINDOW,
        )
        if diff.returncode == 0:
            log("earnings_calendar.csv 변경 없음 - push 건너뜀")
            return
        commit = subprocess.run(
            ["git", "commit", "-m", "Update earnings_calendar.csv",
             "-m", "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"],
            cwd=CODE_DIR, capture_output=True, text=True, timeout=30, creationflags=CREATE_NO_WINDOW,
        )
        if commit.returncode != 0:
            log(f"git commit 실패(무시하고 계속함): {commit.stderr.strip()}")
            return
        push = subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=CODE_DIR, capture_output=True, text=True, timeout=60, creationflags=CREATE_NO_WINDOW,
        )
        if push.returncode == 0:
            log("earnings_calendar.csv GitHub push 완료")
        else:
            log(f"git push 실패(무시하고 계속함): {push.stderr.strip()}")
    except Exception as e:
        log(f"git push 중 오류(무시하고 계속함): {e}")


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
    git_pull()
    ok = True
    for script in SCRIPTS:
        if not run_script(script):
            ok = False
    git_push_calendar()

    if not run_script("sync_to_server.py"):
        ok = False

    log("일일 배치 종료" + ("" if ok else " (일부 실패)"))
    if ok:
        mark_success_today()


if __name__ == "__main__":
    main()

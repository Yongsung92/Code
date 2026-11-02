"""
code/dashboard.html과 earnings/의 실적 캘린더·요약을 AWS Lightsail 서버로 올려서
공개 대시보드의 실적 탭을 최신 상태로 유지한다.

올리는 것: companies.csv, earnings_calendar.csv(날짜는 사실관계라 공개해도 된다),
summary/ 폴더(실적 콜 내용에서 주제를 뽑아 사람이 직접 재구성한 원본 요약 - 전문을
그대로 옮긴 게 아니라 공개해도 된다).
올리지 않는 것: 이 폴더는 애초에 실적 콜 "전문"을 저장하지 않는다. 전문은
저작권 있는 콘텐츠라 로컬에도 쌓아두지 않고, 요약을 쓸 때만 그때그때 참고한다.
"""
import os
import subprocess
import sys

SERVER_HOST = "ubuntu@43.202.57.224"
SERVER_PATH = "/var/www/etf-dashboard"
TIMEOUT_SEC = 60
# pythonw.exe(콘솔 없음)가 ssh/scp(콘솔 앱)를 띄우면 윈도우가 새 콘솔 창을 만들어 버린다 -
# 배치가 조용히 돌도록 창을 띄우지 않는다.
CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

EARNINGS_DIR = os.path.dirname(os.path.abspath(__file__))
CODE_DIR = os.path.dirname(EARNINGS_DIR)
KEY_PATH = os.path.join(CODE_DIR, "LightsailDefaultKey-ap-northeast-2.pem")
SUMMARY_DIR = os.path.join(EARNINGS_DIR, "summary")

DASHBOARD_FILE = os.path.join(CODE_DIR, "dashboard.html")
CSV_FILES = [
    os.path.join(EARNINGS_DIR, "companies.csv"),
    os.path.join(EARNINGS_DIR, "earnings_calendar.csv"),
]


def _scp(files: list, remote_dir: str) -> bool:
    files = [f for f in files if os.path.exists(f)]
    if not files:
        return True
    cmd = [
        "scp", "-i", KEY_PATH, "-o", "StrictHostKeyChecking=accept-new",
        "-o", f"ConnectTimeout={TIMEOUT_SEC}",
        *files, f"{SERVER_HOST}:{remote_dir}",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_SEC, creationflags=CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        print(f"업로드 실패({remote_dir}): {TIMEOUT_SEC}초 안에 응답이 없어 중단함")
        return False
    if result.returncode != 0:
        print(f"업로드 실패({remote_dir}): {result.stderr.strip()}")
        return False
    return True


def main() -> bool:
    if not os.path.exists(KEY_PATH):
        print(f"SSH 키를 찾을 수 없습니다: {KEY_PATH}")
        return False

    try:
        mkdir = subprocess.run(
            ["ssh", "-i", KEY_PATH, "-o", "StrictHostKeyChecking=accept-new",
             "-o", f"ConnectTimeout={TIMEOUT_SEC}",
             SERVER_HOST, f"mkdir -p {SERVER_PATH}/earnings/summary"],
            capture_output=True, text=True, timeout=TIMEOUT_SEC, creationflags=CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        print(f"원격 디렉터리 생성 실패: {TIMEOUT_SEC}초 안에 응답이 없어 중단함")
        return False
    if mkdir.returncode != 0:
        print(f"원격 디렉터리 생성 실패: {mkdir.stderr.strip()}")
        return False

    ok = _scp([DASHBOARD_FILE], SERVER_PATH)
    ok = _scp(CSV_FILES, f"{SERVER_PATH}/earnings") and ok

    if os.path.isdir(SUMMARY_DIR):
        summary_files = [os.path.join(SUMMARY_DIR, name) for name in os.listdir(SUMMARY_DIR) if name.endswith(".txt")]
        ok = _scp(summary_files, f"{SERVER_PATH}/earnings/summary") and ok

    if ok:
        print("Lightsail 대시보드 업로드 완료.")
    return ok


if __name__ == "__main__":
    sys.exit(0 if main() else 1)

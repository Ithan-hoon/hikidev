"""YouTube 업로드용 OAuth refresh token 을 한 번 받는다. 주인이 호스트에서 돌린다.

    uv run --with google-auth-oauthlib scripts/youtube_auth.py <client_secret.json> [--scopes SCOPE ...]

구글 클라우드 콘솔에서 받은 OAuth "데스크톱 앱" 클라이언트 JSON 을 넘기면 브라우저가 열리고,
hikidev 전용 구글 계정으로 동의하면 .env 에 붙일 세 줄을 stdout 에 찍는다. 파일엔 아무것도 쓰지 않는다.
토큰은 .env 에만 둔다 — 코드·yaml·테스트에 넣지 않는다.

기본 범위는 업로드만 (https://www.googleapis.com/auth/youtube.upload). 더 필요하면 --scopes 로 덧붙인다.
"""

from __future__ import annotations

import argparse
import sys

UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
NO_REFRESH_HINT = (
    "refresh token 이 안 왔다. 이 계정이 이 앱에 이미 동의한 적이 있으면 구글은 새 refresh token 을 주지 않는다.\n"
    "구글 계정 > 보안 > 서드파티 앱 및 서비스에서 이 앱의 접근을 끊고 다시 돌려라."
)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows cp949 콘솔에서 한글·기호가 깨지지 않게
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("client_secret", help="구글 콘솔에서 받은 OAuth 데스크톱 클라이언트 JSON 경로")
    ap.add_argument("--scopes", nargs="*", default=[], help=f"추가 범위 (기본 {UPLOAD_SCOPE})")
    args = ap.parse_args(argv)

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        sys.exit("google-auth-oauthlib 가 없다: uv run --with google-auth-oauthlib scripts/youtube_auth.py ...")

    scopes = [UPLOAD_SCOPE, *[s for s in args.scopes if s != UPLOAD_SCOPE]]
    flow = InstalledAppFlow.from_client_secrets_file(args.client_secret, scopes=scopes)
    # access_type=offline 이어야 refresh token 이 오고, prompt=consent 로 재동의를 강제해
    # '이미 동의함' 때문에 refresh token 이 빠지는 걸 막는다
    creds = flow.run_local_server(port=0, open_browser=True, access_type="offline", prompt="consent")

    if not creds.refresh_token:
        print(NO_REFRESH_HINT, file=sys.stderr)
        return 1

    print("# .env 에 붙여 넣기 (hikidev 전용 계정, 업로드 권한만)")
    print(f"YOUTUBE_CLIENT_ID={creds.client_id}")
    print(f"YOUTUBE_CLIENT_SECRET={creds.client_secret}")
    print(f"YOUTUBE_REFRESH_TOKEN={creds.refresh_token}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

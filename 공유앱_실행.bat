@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
echo ============================================================
echo   ECKASA 광고 스튜디오 - 공개 링크 실행
echo ============================================================
echo.
echo  [1/2] 앱 서버를 켭니다...
start "ECKASA 서버 (끄지 마세요)" ".venv\Scripts\python.exe" run.py
timeout /t 6 >nul
echo  [2/2] 공개 링크(터널)를 켭니다...
echo.
echo  ▼▼▼ 아래에 표시되는 https://...trycloudflare.com  주소가 '내 앱 링크' 입니다 ▼▼▼
echo      (로그인:  아이디 eckasa  /  비밀번호는 .env 의 APP_PASSWORD)
echo      이 창과 'ECKASA 서버' 창을 닫으면 링크가 꺼집니다.
echo.
"tools\cloudflared.exe" tunnel --url http://127.0.0.1:8000
pause

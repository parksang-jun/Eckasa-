@echo off
chcp 65001 >nul
title ECKASA 자동운영 서버 - 이 창을 켜 두세요
cd /d "%~dp0자동운영"
echo.
echo  에카사 자동운영 서버를 시작합니다...
echo  잠시 후 브라우저가 자동으로 열립니다. (http://localhost:8930)
echo  이 창을 닫으면 자동운영이 멈춥니다. 최소화만 해 두세요.
echo.
python server.py
echo.
echo  서버가 종료되었습니다. 오류가 보이면 이 창을 캡처해 두세요.
pause

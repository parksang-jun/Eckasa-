"""대시보드 실행 진입점.

  python run.py            # http://127.0.0.1:8000 에서 대시보드 실행
"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)

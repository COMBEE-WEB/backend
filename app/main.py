from fastapi import FastAPI

app = FastAPI(title="COMBEE API")


#-------------------
# 서버 상태 확인
#-------------------
@app.get("/health")
def get_health():
    return {"status": "ok"}
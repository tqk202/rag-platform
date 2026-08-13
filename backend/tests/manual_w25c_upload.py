"""W2.5c 演示数据上传：注册 hr 用户，上传 3 份演示文档。"""
import time

import httpx

BASE = "http://localhost:8000/api/v1"
DOCS = [
    r"d:\AI coding\RAG\backend\demo_docs\员工考勤与加班管理制度.txt",
    r"d:\AI coding\RAG\backend\demo_docs\费用报销管理制度.txt",
    r"d:\AI coding\RAG\backend\demo_docs\年假与休假管理制度.txt",
    r"d:\AI coding\RAG\backend\demo_docs\差旅与住宿标准.txt",
    r"d:\AI coding\RAG\backend\demo_docs\培训与职业发展制度.txt",
]

user = {"username": f"hr_{int(time.time())}", "password": "test123456", "department": "hr"}

with httpx.Client(timeout=90) as c:
    c.post(f"{BASE}/auth/register", json=user)
    tok = c.post(f"{BASE}/auth/login", json={"username": user["username"], "password": user["password"]}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    for path in DOCS:
        name = path.rsplit("\\", 1)[-1]
        with open(path, "rb") as f:
            r = c.post(f"{BASE}/documents/upload", headers=h, files={"file": (name, f, "text/plain")})
        print(name, r.status_code, r.json())
    lst = c.get(f"{BASE}/documents", headers=h).json()
    print("部门文档总数:", lst["total"])

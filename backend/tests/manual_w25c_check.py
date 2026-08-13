"""W2.5c 重排端到端实测：注册/登录 -> 流式问答，SSE 结果写 UTF-8 文件。"""
import json
import time

import httpx

BASE = "http://localhost:8000/api/v1"
OUT = r"d:\AI coding\RAG\backend\w25c_check_out.txt"

user = {"username": f"w25c_{int(time.time())}", "password": "test123456", "department": "hr"}

QUESTIONS = [
    "报销款项什么时候发放？发票有什么要求？",
    "加班费怎么算？",
    "年假每年几天？离职时未休年假怎么处理？",
    "出差住宿标准是多少？交通费能报销什么？",
    "请假和年假怎么申请？",
    "今天天气怎么样",
]


def main():
    lines = []
    with httpx.Client(timeout=90) as c:
        c.post(f"{BASE}/auth/register", json=user)
        tok = c.post(f"{BASE}/auth/login", json={"username": user["username"], "password": user["password"]}).json()["access_token"]
        headers = {"Authorization": f"Bearer {tok}"}
        lines.append(f"用户: {user['username']} @ {user['department']}")

        for q in QUESTIONS:
            lines.append(f"\n=== 问题: {q} ===")
            events = []
            with c.stream("POST", f"{BASE}/chat/stream", headers=headers, json={"question": q, "history": []}) as r:
                buf = ""
                for chunk in r.iter_text():
                    buf += chunk
                    while "\n\n" in buf:
                        block, buf = buf.split("\n\n", 1)
                        ev, data = None, None
                        for line in block.splitlines():
                            if line.startswith("event:"):
                                ev = line[6:].strip()
                            elif line.startswith("data:"):
                                data = line[5:].strip()
                        if ev:
                            try:
                                events.append((ev, json.loads(data) if data else None))
                            except json.JSONDecodeError:
                                events.append((ev, data))
            for ev, data in events:
                if ev == "meta":
                    order = "; ".join(
                        f"[{d['no']}]{d['document_title']}:{d['snippet'][:14]}"
                        for d in data["chunks"]
                    )
                    lines.append(f"[meta] {data['chunk_count']} 条顺序 -> {order}")
                elif ev == "delta":
                    pass  # 太多，不打印
                elif ev == "done":
                    lines.append(f"[done] no_answer={data['no_answer']}")
                    lines.append(f"[done] 回答: {data['answer']}")
                    lines.append(f"[done] 引文: {[x['document_title'] for x in data['citations']]}")

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("written:", OUT)


if __name__ == "__main__":
    main()

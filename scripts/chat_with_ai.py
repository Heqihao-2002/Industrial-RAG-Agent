import requests
import json
import time

# 该脚本实现连续三次问答，自动发送问题并输出 AI 回复，模拟多轮交互
print(">>> 客户端脚本开始运行，准备发送请求...")


chat_url = "http://127.0.0.1:8000/chat"
headers = {"Content-Type": "application/json"}

# 准备 3 个问题
questions = [
    "该研究团队的人员构成是怎样的？",
    "这个团队里副教授有几位？",
    "团队中有没有研究生？"
]

session_id = "demo_multiround"  # 多轮对话使用同一个 session_id

for idx, q in enumerate(questions, 1):
    payload = {
        "message": q,
        "session_id": session_id  # 保证连续多轮
    }

    response = requests.post(chat_url, headers=headers, data=json.dumps(payload), stream=True)

    print(f"\n第{idx}问：{q}\nAI 回复：", end="", flush=True)

    # 流式输出 AI 的回复内容，模拟打字机效果
    for line in response.iter_lines(decode_unicode=True):
        if not line:
            continue
        if line.startswith("data:"):
            content = line[len("data:"):].strip()
            if content == "[DONE]":
                break
            print(content, end="", flush=True)
            time.sleep(0.05)  # 控制输出速度

    print()  # 换行

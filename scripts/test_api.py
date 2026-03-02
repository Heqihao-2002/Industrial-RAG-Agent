import requests
import sys
import time

def test_chat_stream():
    """
    用于测试 /chat 接口的流式输出，模拟打字机效果。
    """
    url = "http://127.0.0.1:8000/chat"  # 假定 FastAPI 运行在本地 8000 端口
    payload = {"message": "你好，AI！请用一句话总结《三体》的故事。"}
    # stream=True 表示支持流式接收响应体
    with requests.post(url, json=payload, stream=True) as response:
        # 确保响应状态正常
        assert response.status_code == 200
        # iter_lines 会分块读取 SSE 格式文本
        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue  # 跳过空行（SSE规范中会有）
            if line.startswith("data:"):
                content = line[5:].strip()  # 去掉 "data:" 前缀和空白
                if content == "[DONE]":
                    print()  # 生成结束，换行
                    break
                # 实现“打字机效果”：每收到一个字符就实时打印，无需等待全部结束
                print(content, end="", flush=True)
                # 可选：模拟稍微慢一点的“打字”（如需体验）
                # time.sleep(0.05)

if __name__ == "__main__":
    # print("准备发送 POST 请求...")
    test_chat_stream()
    # print("测试脚本运行结束。") 
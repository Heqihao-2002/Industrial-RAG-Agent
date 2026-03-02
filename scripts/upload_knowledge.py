import requests
import os

# 1. 动态计算文件的绝对路径
current_dir = os.path.dirname(os.path.abspath(__file__))
# 逻辑：当前脚本(scripts) -> 上一级(根目录) -> data -> knowledge.txt
file_path = os.path.join(current_dir, "..", "data", "knowledge.txt")

# 2. 上传知识文档
upload_url = "http://127.0.0.1:8000/upload"

# 关键改动：使用 file_path 变量，而不是写死的文件名
if not os.path.exists(file_path):
    print(f"❌ 错误：找不到文件，预期的路径是: {file_path}")
else:
    with open(file_path, "rb") as f:
        # file 字段的元数据也建议保持一致
        files = {"file": (os.path.basename(file_path), f, "text/plain")}
        try:
            response = requests.post(upload_url, files=files)
            print("✅ 上传结果：", response.json())
        except Exception as e:
            print(f"❌ 请求失败：{e}")
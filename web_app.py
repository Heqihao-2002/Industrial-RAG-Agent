import streamlit as st
import requests
import uuid

# ------- 页面标题与 session_id、聊天历史管理 -------
st.set_page_config(page_title="跨境电商智能 RAG 助手", page_icon="🤖", layout="wide")
st.title("🛒 跨境电商智能客服")

# 生成并持久化 session_id 保证多轮状态
if "session_id" not in st.session_state:
    st.session_state["session_id"] = str(uuid.uuid4())
# 使用 messages 存储对话历史，每则消息为 dict: {'role': 'user'|'ai', 'content': ...}
if "messages" not in st.session_state:
    st.session_state["messages"] = []

# ------- 侧边栏：文件上传与显示上传状态 -------
with st.sidebar:
    st.header("📚 上传产品手册/售后政策 (PDF/TXT)")
    upload_status = st.empty()
    uploaded_file = st.file_uploader(
        "选择PDF或TXT文件上传", 
        type=['pdf', 'txt'],
        help="支持 .pdf 和 .txt 格式"
    )

    # 文件上传逻辑
    if uploaded_file is not None:
        # 上传到后端API
        upload_status.info("正在上传，请稍候...")
        files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
        try:
            # 直接同步上传，流式与异步暂不支持
            resp = requests.post("http://127.0.0.1:8000/upload", files=files, timeout=60)
            if resp.status_code == 200:
                upload_status.success(f"上传成功: {resp.json().get('message','')}")
            else:
                upload_status.error(f"上传失败: {resp.text}")
        except Exception as e:
            upload_status.error(f"上传异常: {str(e)}")

# ------- 主界面：聊天窗口呈现 -------
st.markdown(
    """
    <style>
    .user-msg {background: #DCF8C6; padding: 8px 12px; border-radius: 8px; margin-bottom:6px; max-width:80%; align-self: flex-end;}
    .ai-msg {background: #F3F3F3; padding: 8px 12px; border-radius: 8px; margin-bottom:6px; max-width:80%; align-self: flex-start;}
    .chat-block {display: flex; flex-direction: column;}
    </style>
    """, unsafe_allow_html=True
)

def stream_ai_reply(question, session_id):
    """
    通过 SSE 流式请求 /chat 接口，yield AI 返回内容片段
    """
    url = "http://127.0.0.1:8000/chat"
    payload = {"message": question, "session_id": session_id}
    headers = {"Content-Type": "application/json"}
    try:
        # 使用 requests 的 stream 模式读取 SSE
        response = requests.post(url, headers=headers, json=payload, stream=True, timeout=180)

        # 逐行处理SSE格式：data: 内容
        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue
            if line.startswith("data:"):
                content = line[len("data:"):].strip()
                if content == "[DONE]":
                    break
                yield content
    except Exception as e:
        # 错误时中止生成并提示
        yield f"\n[系统提示] AI接口调用出错：{str(e)}"

# ------- 用户输入，用官方 st.chat_input 方式处理 -------
# 由于要做到“每次提问后主界面立刻展示问题和答案”，需要
# 先在主界面渲染历史消息，然后在有新输入时，先插入用户对话，再生成AI回复，再插入AI回复，再刷新全部渲染。

# 获取用户输入
prompt = st.chat_input("请输入您要咨询的产品参数或退换货政策...（如：该产品的核心产品参数？）")

# ------- 渲染历史消息（问题和答案一问一答对齐展示） -------
# 遍历历史，每次都依次渲染（实现“问题之后跟答案”）
for idx, msg in enumerate(st.session_state["messages"]):
    if msg["role"] == "user":
        with st.chat_message("user"):
            st.markdown(msg["content"])
        # 展示紧跟的AI回复（如果有）
        if idx + 1 < len(st.session_state["messages"]) and st.session_state["messages"][idx + 1]["role"] == "ai":
            with st.chat_message("ai"):
                st.markdown(st.session_state["messages"][idx + 1]["content"])

# ------- 新问题触发：将用户问题和AI回复插入历史并立即按一问一答结构刷新显示 -------
if prompt:
    # 把当前问题追加到历史
    st.session_state["messages"].append({"role": "user", "content": prompt})

    # 先渲染提问（立即可见）
    with st.chat_message("user"):
        st.markdown(prompt)

    # AI回复流式显示
    ai_reply_chunks = []  # 保存AI分片

    with st.chat_message("ai"):
        reply_placeholder = st.empty()
        def sse_writer():
            # 按块yield AI回复并累积内容
            for chunk in stream_ai_reply(prompt, st.session_state["session_id"]):
                ai_reply_chunks.append(chunk)
                yield chunk
        # 实时渲染AI回答
        reply_placeholder.write_stream(sse_writer)

    # 拼接完整AI回答，写入历史
    full_reply = "".join(ai_reply_chunks)
    st.session_state["messages"].append({"role": "ai", "content": full_reply})

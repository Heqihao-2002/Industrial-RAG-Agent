import streamlit as st
import requests
import pandas as pd
import mysql.connector
import os
from dotenv import load_dotenv
import uuid

# 加载配置
load_dotenv()

# --- 1. 页面配置 ---
st.set_page_config(page_title="跨境电商智能客服管理系统", layout="wide")

# --- 2. 侧边栏导航 ---
st.sidebar.title("🚀 导航中心")
page = st.sidebar.radio("请选择功能模块：", ["智能客服对话", "数据审计后台"])

BACKEND_URL = "http://127.0.0.1:8000"

# --- 模块一：智能客服对话 ---
if page == "智能客服对话":
    st.title("🛒 跨境电商智能客服 Agent")
    
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())

    # 侧边栏上传
    with st.sidebar:
        st.divider()
        st.header("📚 知识库管理")
        uploaded_file = st.file_uploader("上传产品手册 (PDF/TXT)", type=["pdf", "txt"])
        if st.button("开始入库"):
            if uploaded_file:
                with st.spinner("正在向量化存入 ChromaDB..."):
                    files = {"file": (uploaded_file.name, uploaded_file.getvalue())}
                    res = requests.post(f"{BACKEND_URL}/upload", files=files)
                    st.success("入库成功！")
            else:
                st.warning("请先选择文件")

    # 聊天展示
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if prompt := st.chat_input("请输入您要咨询的产品问题..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            placeholder = st.empty()
            full_res = ""
            payload = {"message": prompt, "session_id": st.session_state.session_id}
            with requests.post(f"{BACKEND_URL}/chat", json=payload, stream=True) as r:
                for line in r.iter_lines(decode_unicode=True):
                    if line and line.startswith("data: "):
                        content = line[6:]
                        if content == "[DONE]": break
                        full_res += content
                        placeholder.markdown(full_res + "▌")
            placeholder.markdown(full_res)
        st.session_state.messages.append({"role": "assistant", "content": full_res})

# --- 模块二：数据审计后台 (MySQL 可视化) ---
elif page == "数据审计后台":
    st.title("📊 大模型通话审计后台")
    st.info("说明：此处数据实时读取自本地 MySQL 数据库，用于业务监控与语料分析。")

    try:
        # 从环境变量解析 MySQL 连接信息（简单处理）
        # 假设你的 MYSQL_URL 是 mysql+aiomysql://root:password@localhost:3306/ai_agent_db
        # 这里为了演示，直接手动填入或从环境变量取
        conn = mysql.connector.connect(
            host="localhost",
            user="root",
            password="123456", 
            database="ai_agent_db"
        )
        
        # 使用 Pandas 读取数据
        query = "SELECT id, session_id, user_query, ai_response, created_at FROM chat_logs ORDER BY created_at DESC"
        df = pd.DataFrame(pd.read_sql(query, conn))
        
        # 数据统计卡片
        col1, col2, col3 = st.columns(3)
        col1.metric("总对话量", len(df))
        col2.metric("活跃 Session 数", df['session_id'].nunique())
        col3.metric("最新更新时间", str(df['created_at'].iloc[0]) if not df.empty else "无数据")

        # 数据表格美化
        st.subheader("📝 全量历史记录")
        # 截断长文本显示，防止表格太丑
        df_display = df.copy()
        df_display['session_id'] = df_display['session_id'].str[:8] + "..."
        
        st.dataframe(
            df_display, 
            column_config={
                "user_query": st.column_config.TextColumn("用户提问", width="medium"),
                "ai_response": st.column_config.TextColumn("AI 回复内容", width="large"),
                "created_at": st.column_config.DatetimeColumn("时间", format="MM-DD HH:mm"),
            },
            hide_index=True,
            use_container_width=True
        )
        
        if st.button("刷新实时数据"):
            st.rerun()

        conn.close()

    except Exception as e:
        st.error(f"无法读取 MySQL 数据库: {e}")
        st.warning("请确保 MySQL 服务已启动且密码配置正确。")
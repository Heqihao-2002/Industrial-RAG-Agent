from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
import asyncio
import os
from dotenv import load_dotenv
import openai
import chromadb
from typing import List
from PyPDF2 import PdfReader
import io
import json
from tavily import TavilyClient
from pathlib import Path

# ==================== 基础配置加载 ====================

env_path = Path(__name__).parent.parent / '.env'
load_dotenv(env_path)
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
DASHSCOPE_BASE_URL = os.getenv("DASHSCOPE_BASE_URL")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
REDIS_URL = os.getenv("REDIS_URL")
MYSQL_URL = os.getenv("MYSQL_URL")

# ==================== 第三方客户端初始化 ====================

# OpenAI 千问大模型异步客户端
client = openai.AsyncOpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url=DASHSCOPE_BASE_URL,
)

# ChromaDB 知识库持久化客户端
chroma_client = chromadb.PersistentClient(path="./chroma_db")
collection = chroma_client.get_or_create_collection(name="my_knowledge_base")

# Tavily 搜索API客户端
tavily_client = TavilyClient(api_key=TAVILY_API_KEY)

# ========== Redis 异步客户端（对话历史记忆） ==========
import redis.asyncio as aioredis
redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)

# ========== SQLAlchemy 异步客户端（日志审计） ==========
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import Column, Integer, String, Text, DateTime, func

Base = declarative_base()

# 明确 chat_logs 的字段名与约束
class ChatLog(Base):
    __tablename__ = "chat_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(128), index=True, nullable=False)
    user_query = Column(Text, nullable=False)
    ai_response = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=func.now())

# 创建异步MySQL引擎&Session工厂
engine = create_async_engine(MYSQL_URL, echo=False, future=True)
async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

# ==================== FastAPI 主应用及 lifespan 钩子 ====================

app = FastAPI()

@app.on_event("startup")
async def lifespan_check():
    """
    系统启动时自动进行依赖服务健康检查，初始化表结构。
    """
    # 检查 MySQL 连接、建表（如无）
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print("[MySQL] 链接和 chat_logs 表结构已检查/初始化")
    except Exception as e:
        print(f"[MySQL] 启动时检查失败: {e}")

    # 检查 Redis 连接
    try:
        pong = await redis_client.ping()
        if pong:
            print("[Redis] 链接正常")
    except Exception as e:
        print(f"[Redis] 启动时检查失败: {e}")

class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"

# ========== 辅助工具函数 ==========

def split_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """
    将长文本分成若干有重叠的较短片段，用于分片存储与召回。
    """
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks

async def get_embedding_real(text: str) -> List[float]:
    """
    请求阿里千问真实 Embedding 接口并获取向量。
    """
    response = await client.embeddings.create(
        model="text-embedding-v3",
        input=text
    )
    return response.data[0].embedding

async def web_search(query: str) -> str:
    """
    使用 Tavily API 查询实时信息，返回主要摘要。
    """
    print("[工具触发] 正在执行互联网实时搜索")
    try:
        result = await asyncio.to_thread(
            tavily_client.search,
            query=query,
            search_depth="advanced",
            include_domains=None,
            include_answer=True,
            max_results=1,
        )
        answer = ""
        if isinstance(result, dict):
            answer = result.get("answer") or ""
            if not answer:
                results_list = result.get("results") or []
                if isinstance(results_list, list) and results_list:
                    first = results_list[0] or {}
                    answer = first.get("content") or first.get("title") or ""
        return answer or "搜索结果为空"
    except Exception as e:
        print(f"[Tavily 异常]: {e}")
        return f"联网搜索失败：{str(e)}"

# ==================== SSE 核心生成器 ====================

async def sse_event_generator(message: str, session_id: str):
    """
    智能对话主流程，串联 RAG/QueryRewrite/Router/互联网搜索，并完成对话历史和日志的异步数据闭环。
    """
    # 1. === （会话记忆）从 Redis 读取历史 ===
    redis_history_key = f"session:{session_id}"
    try:
        his_json = await redis_client.get(redis_history_key)
        # 反序列化后的历史格式: List[dict]，记录最近6条
        history: List[dict] = json.loads(his_json) if his_json else []
    except Exception as e:
        print(f"[Redis] 获取对话历史失败: {e}")
        history = []

    history = history[-6:] if history else []

    # 2. === 意图路由器：决定走本地RAG还是联网搜索 ===
    router_messages = [
        {
            "role": "system",
            "content": (
                "你是一个智能路由中枢。用户的本地知识库中仅包含【AeroX 4K 智能折叠无人机】等特定私有科研资料。\n"
                "请判断用户的提问：\n"
                "1.如果提问与上述【私有项目/本地资料】相关，请仅输出“否”（走本地RAG）。\n"
                "2.如果是其它公众知识，请仅输出“是”（走联网搜索）。"
            )
        }
    ]
    router_messages.extend(history)
    router_messages.append({
        "role": "user",
        "content": f"请判断该问题是否应走联网搜索，仅输出“是”或“否”即可：{message}"
    })

    need_web = False
    try:
        router_resp = await client.chat.completions.create(
            model="qwen-plus",
            messages=router_messages,
            stream=False,
        )
        router_answer = (router_resp.choices[0].message.content or "").strip()
        router_answer_norm = router_answer.replace("。", "").replace(".", "").strip()
        need_web = router_answer_norm.startswith("是")
        print(f"[Router] 智能判断: '{router_answer_norm}' -> need_web={need_web}")
    except Exception as e:
        print(f"[Router 异常，默认走本地RAG]: {e}")
        need_web = False

    # 3. === 检索阶段：RAG/QueryRewrite或互联网搜索 ===
    context = ""
    context_source = "rag"
    if need_web:
        # --- 联网获取外部数据 ---
        context = await web_search(message)
        context_source = "web"
    else:
        # --- 本地知识库 RAG 检索（需先Query Rewrite）---
        rewrite_prompt = [
            {"role": "system", "content": (
                "你是搜索专家，请将用户问题改写为独立精准的知识检索词，只输出关键词，不要解释。"
            )}
        ]
        rewrite_prompt.extend(history)
        rewrite_prompt.append({"role": "user", "content": f"请改写用于本地知识库检索：{message}"})
        try:
            rewrite_resp = await client.chat.completions.create(
                model="qwen-plus",
                messages=rewrite_prompt,
                stream=False,
            )
            search_query = rewrite_resp.choices[0].message.content.strip()
        except Exception as e:
            search_query = message
            print(f"[RAG改写异常：{e}] 直接用原问题检索")

        # 本地向量库语义检索
        try:
            query_vector = await get_embedding_real(search_query)
            results = collection.query(
                query_embeddings=[query_vector],
                n_results=3,
            )
            documents = results.get("documents") or []
            if documents and documents[0]:
                context = "\n".join(documents[0])
            else:
                context = ""
            print(f"[RAG] 检索结果(截断): {context[:80]}...")
        except Exception as e:
            context = ""
            print(f"[RAG 检索异常]: {e}")

    # 4. === Prompt 构造和流式大模型生成 ===
    if context_source == "web":
        source_desc = "以下资料来自公网实时搜索："
    elif context:
        source_desc = "以下资料来自你的私有知识库："
    else:
        source_desc = "目前无任何资料（知识库无结果，联网未触发）"

    system_prompt = (
        "你是一名智能助理，会参考给定资料和常识回答用户：\n"
        "1. 有资料优先用资料要点，但要自然表达。\n"
        "2. 没有资料可用常识补充。\n"
        "3. 实在答不了请回复‘知识库或联网搜索暂无相关信息’。\n\n"
        f"{source_desc}\n{context}"
    )

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": message})

    stream = await client.chat.completions.create(
        model="qwen-plus",
        messages=messages,
        stream=True
    )

    # ========== 5. 大模型内容流式输出 ==========
    full_reply = ""
    async for chunk in stream:
        delta = chunk.choices[0].delta
        if hasattr(delta, "content") and delta.content:
            full_reply += delta.content
            yield f"data: {delta.content}\n\n"

    # 6. === 会话记忆/日志 — 把对话追加回 Redis，并写入MySQL日志 ===
    # Redis历史更新：追加本轮问答，只保留最近6条
    history.append({"role": "user", "content": message})
    history.append({"role": "assistant", "content": full_reply})
    trimmed = history[-6:]
    try:
        await redis_client.set(redis_history_key, json.dumps(trimmed, ensure_ascii=False))
        await redis_client.expire(redis_history_key, 60 * 60)   # 1小时自动过期
    except Exception as e:
        print(f"[Redis] 写入历史失败: {e}")

    # MySQL持久化日志
    try:
        async with async_session() as db:
            record = ChatLog(
                session_id=session_id,
                user_query=message,
                ai_response=full_reply,
                created_at=None # 由数据库NOW()生成
            )
            db.add(record)
            await db.commit()
    except Exception as e:
        print(f"[MySQL] 写入 chat_logs 失败: {e}")

    yield "data: [DONE]\n\n"

# ==================== 文档分片上传接口 ====================

@app.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    """
    支持 txt/pdf 文件上传并自动分片入库（嵌入知识库）。
    """
    if file.filename.endswith(".pdf"):
        content_buffer = await file.read()
        pdf_reader = PdfReader(io.BytesIO(content_buffer))
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() or ""
        content = text
    else:
        content = (await file.read()).decode("utf-8")

    # 分片并存入向量库
    chunks = split_text(content)
    for i, chunk in enumerate(chunks):
        vector = await get_embedding_real(chunk)
        collection.add(
            ids=[f"{file.filename}_{i}"],
            embeddings=[vector],
            documents=[chunk],
            metadatas=[{"source": file.filename}]
        )
    return {"message": f"成功入库 {len(chunks)} 个片段"}

# ==================== 对话入口 ====================

@app.post("/chat")
async def chat_stream(chat_request: ChatRequest):
    """
    对话接口。自动判断走RAG还是走Agent(web-search)。
    SSE流式返回LLM内容，历史由Redis管理，日志由MySQL记录。
    """
    return StreamingResponse(
        sse_event_generator(chat_request.message, chat_request.session_id),
        media_type='text/event-stream'
    )
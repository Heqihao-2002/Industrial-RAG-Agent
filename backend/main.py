from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
import asyncio
from fastapi.responses import StreamingResponse
import os
from dotenv import load_dotenv
import openai
import chromadb
from typing import List
from PyPDF2 import PdfReader
import io

# 引入tavily-python库，用于联网搜索
from tavily import TavilyClient
from pathlib import Path
env_path = Path(__name__).parent.parent / '.env'
# 1. 加载配置
load_dotenv()
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
DASHSCOPE_BASE_URL = os.getenv("DASHSCOPE_BASE_URL")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")  # 必须在.env中设置

# 2. 初始化 OpenAI 客户端
client = openai.AsyncOpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url=DASHSCOPE_BASE_URL,
)

# 3. 初始化 ChromaDB
chroma_client = chromadb.PersistentClient(path="./chroma_db")
collection = chroma_client.get_or_create_collection(name="my_knowledge_base")

# 4. Tavily 搜索客户端
tavily_client = TavilyClient(api_key=TAVILY_API_KEY)

app = FastAPI()
session_history = {}

class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"

# --- 工具函数 ---

def split_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """
    将文本分成若干有重叠的片段，用于片段向量化与召回
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
    调用阿里千问真实 Embedding 接口获取向量
    """
    response = await client.embeddings.create(
        model="text-embedding-v3",
        input=text
    )
    return response.data[0].embedding

async def web_search(query: str) -> str:
    """
    使用 Tavily API 进行联网搜索，返回主要摘要结果
    """
    print("[工具触发] 正在执行搜索")
    try:
        # 官方为同步接口，此处转线程防阻塞
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

# --- 核心 SSE 生成器 ---

async def sse_event_generator(message: str, session_id: str):
    """
    对话生成主流程：
    1. 调用Router确定本地还是外网
    2. RAG分片/向量召回或执行WEB搜索
    3. 统一流式输出
    """
    # 0. 获取会话历史
    history = session_history.get(session_id, [])[-6:]

    # 1. 路由意图识别，分辨本地资料还是联网（定制化业务 prompt）
    router_messages = [
        {
            "role": "system",
            "content": (
                "你是一个智能路由中枢。用户的本地知识库中仅包含【工业设备多模态智能故障诊断项目、量子猫架项目、人员构成】等特定的私有科研资料。\n"
                "请判断用户的提问：\n"
                "1.如果提问与上述【私有项目/本地资料】相关，请仅输出“否”（代表走本地RAG）。\n"
                "2.如果提问是关于【大学地址、天气、公众新闻、历史常识】等不属于上述私有项目的外部知识，请仅输出“是”（代表走联网搜索）。"
            )
        }
    ]
    router_messages.extend(history)
    router_messages.append(
        {
            "role": "user",
            "content": f"请判断该问题是否应走联网搜索，仅输出“是”或“否”即可：{message}"
        }
    )

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
        print(f"[Router 调用异常，默认不联网]: {e}")
        need_web = False

    # 2. RAG相关
    context = ""
    context_source = "rag"

    if need_web:
        # 需要联网：仅在后端控制台打印提示，前端不再展示“正在联网搜索...”字样
        context = await web_search(message)
        context_source = "web"
    else:
        # 本地RAG走 Query Rewrite
        rewrite_prompt = [
            {
                "role": "system",
                "content": (
                    "你是搜索专家，请结合历史，将用户提问改写为独立精准的知识库检索关键词，只输出关键词，不需要任何解释。"
                ),
            }
        ]
        rewrite_prompt.extend(history)
        rewrite_prompt.append(
            {"role": "user", "content": f"请改写用于本地知识库检索：{message}"}
        )
        try:
            rewrite_resp = await client.chat.completions.create(
                model="qwen-plus",
                messages=rewrite_prompt,
                stream=False,
            )
            search_query = rewrite_resp.choices[0].message.content.strip()
            print(f"[RAG] 原始问题: {message}")
            print(f"[RAG] 重写检索词: {search_query}")
        except Exception as e:
            search_query = message
            print(f"[RAG重写异常，回退]: {e}")

        # 检索本地知识库
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
        except Exception as e:
            context = ""
            print(f"[RAG 检索异常]: {e}")

        context_source = "rag"
        print(f"[RAG] 检索上下文(截断): {context[:100]}...")

    # 3. Prompt 构造与流式生成
    if context_source == "web":
        source_desc = "以下资料来自公网实时搜索："
    elif context:
        source_desc = "以下资料来自你的私有知识库："
    else:
        source_desc = "目前无任何资料（知识库无结果，联网未触发）"

    system_prompt = (
        "你是一名中文智能助理，会参考给定资料和你自身常识来回答用户问题：\n"
        "1. 有资料时优先用资料要点，但避免生搬硬套。\n"
        "2. 没资料时可用你已有常识补充。\n"
        "3. 如两者都无法解答，请直接说‘知识库或联网搜索中暂无相关信息’。\n\n"
        f"{source_desc}\n{context}"
    )

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": message})

    # 保持输出流模式
    stream = await client.chat.completions.create(
        model="qwen-plus",
        messages=messages,
        stream=True
    )

    full_reply = ""
    async for chunk in stream:
        delta = chunk.choices[0].delta
        if hasattr(delta, "content") and delta.content:
            full_reply += delta.content
            yield f"data: {delta.content}\n\n"
    yield "data: [DONE]\n\n"

    # 更新对话历史
    history.append({"role": "user", "content": message})
    history.append({"role": "assistant", "content": full_reply})
    session_history[session_id] = history[-6:]

# --- 路由配置 ---

@app.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    """
    支持 txt/pdf 文件上传并分片入库
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

@app.post("/chat")
async def chat_stream(chat_request: ChatRequest):
    """
    对话接口。自动判断走RAG还是走Agent（集成web搜索）
    流式返回LLM内容
    """
    return StreamingResponse(
        sse_event_generator(chat_request.message, chat_request.session_id),
        media_type='text/event-stream'
    )
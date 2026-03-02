# 🤖 工业智能知识库 Agent 系统 (Industrial RAG Agent)

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Asynchronous-009688.svg)](https://fastapi.tiangolo.com/)
[![Streamlit](https://img.shields.io/badge/Streamlit-UI-FF4B4B.svg)](https://streamlit.io/)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-Vector_Store-orange.svg)](https://www.trychroma.com/)

> **🎯 研发初衷**：本项目旨在解决通用大模型在垂直工业场景下的“知识幻觉”与“实时信息滞后”问题。通过构建端到端的 RAG + Agent 架构，实现私有文档的高精度问答与外网实时数据的智能调度。

<img src="./screenshot.png" alt="项目演示截图" width="700" />


---

## 🌟 核心技术与工程亮点 (Core Features)

本项目拒绝简单的 API 堆砌，重点攻克了 AI Agent 落地过程中的 4 个核心工程痛点：

### 1. 🚦 智能意图路由 (LLM-based Intent Routing)
- **痛点**：传统 RAG 系统无法回答知识库之外的实时问题。
- **解法**：在检索前置入轻量级 Router 节点，自动分类用户意图。私有知识走 **ChromaDB 本地检索**，实时常识/新闻自动切走 **Tavily Web Search 链路**，实现“私有库+公网”的混合调度。

### 2. 🔄 多轮对话记忆与查询重写 (Query Rewrite)
- **痛点**：用户在多轮对话中常使用代词（如“那副教授呢？”），导致向量检索由于“语义漂移”而召回失败。
- **解法**：引入 `Session History` 维护上下文（滑动窗口机制），并在检索前利用 LLM 进行 **Query Transformation**，将口语化提问重写为独立的精准搜索词，使 RAG 的召回准确率显著提升。

### 3. 📚 工业级 RAG 流水线 (Production-ready RAG)
- **入库链路**：实现 `PdfReader` 文档解析，采用 `500字 + 50字 Overlap` 的滑动窗口切片算法，有效防止语义截断。
- **向量化**：接入阿里云 `text-embedding-v3` 模型，将文本映射为 1536 维语义坐标，并持久化存储至本地 ChromaDB 引擎，实现毫秒级余弦相似度检索。

### 4. ⚡ 全链路异步流式响应 (Asynchronous Streaming)
- **体验优化**：后端采用 FastAPI 原生 `async/await` 架构处理高并发 I/O；
- **协议对接**：通过底层 Python 异步生成器封装 **SSE (Server-Sent Events)** 协议，前端配合 Streamlit 动态组件，实现打字机般丝滑的逐字渲染，将首字响应延迟（TTFT）压缩至最低。

---

## 🛠️ 技术栈清单 (Tech Stack)

- **核心框架**：`FastAPI`, `Uvicorn`, `Pydantic`
- **前端交互**：`Streamlit`
- **AI 基础设施**：
  - **LLM**: 阿里云通义千问 (`qwen-plus`)
  - **Embedding**: `text-embedding-v3`
  - **Vector DB**: `ChromaDB` (Persistent 模式)
  - **Tool Use**: `Tavily Search API` (实时联网增强)

---

## 📂 项目结构 (Project Structure)

遵循生产环境下的模块化解耦规范：

```text
AI_AGENT_PROJECT/
├── backend/                  # 后端核心服务
│   └── main.py               # FastAPI 路由、RAG 逻辑与 Agent 编排
├── scripts/                  # 自动化测试与运维脚本
│   ├── upload_knowledge.py   # 离线知识入库脚本 (管理员用)
│   ├── chat_with_ai.py       # 终端对话流式测试脚本
│   └── test_api.py           # 接口状态验证
├── data/                     # 原始业务语料库 (Git 忽略)
│   └── knowledge.txt         
├── chroma_db/                # Chroma 本地持久化向量索引 (Git 忽略)
├── web_app.py                # Streamlit Web 端入口
├── requirements.txt          # 核心依赖清单
└── .env.example              # 环境变量配置模板
```

## 🚥 快速启动 (Getting Started)

### 1. 环境安装
克隆本项目后，在项目根目录安装核心依赖：
```bash
pip install -r requirements.txt
```
### 2. 配置环境变量
在根目录新建 .env 文件，填入你的 API Keys（可参考 .env.example）：
```bash
DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxx
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
TAVILY_API_KEY=tvly-xxxxxxxxxxxxxxx
```
### 3. 启动服务 (需开启两个终端)
终端 1：启动 FastAPI 后端推理中心
```bash
uvicorn backend.main:app --reload
```
终端 2：启动 Streamlit 前端交互界面
```bash
streamlit run web_app.py
```
服务启动后，浏览器将自动打开 http://localhost:8501。请先在网页侧边栏上传测试文档，即可开始智能对话。


## 📈 后续演进计划 (Roadmap v2.0)
- [ ] 接入 **Redis**，将内存级的 Session 字典升级为分布式高可用会话存储。
- [ ] 引入 **Reranker (重排模型)** 结合 BM25 实现混合检索 (Hybrid Search)。
- [ ] 构建 **Ragas 评测管道**，实现系统 Faithfulness 与 Answer Relevance 的定量评估。


👨‍💻 Author: [贺奇豪] | 杭州电子科技大学 (HDU)
🎯 Objective: 寻找 AI Agent 研发 / 后端开发实习机会
import os
import json
import logging
import httpx
import uvicorn
import openai
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from sse_starlette.sse import EventSourceResponse
from contextlib import asynccontextmanager

# --- 配置与初始化 ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# API Key 配置（优先读取环境变量，这是 Zeabur 部署的关键）
KIMI_KEY = os.getenv("KIMI_KEY", "sk-TwR4oPmZFW7ljDZL7QK8FVp7hxEZHTMo0knLgj1RFLzurlxo").strip()
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "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").strip()

# 系统提示词：设定助手身份与核心事实
SYSTEM_PROMPT = """你是华理信管小助手。
今天是 2026年1月20日（星期二）。

【固定事实库】：
1. 2026年寒假时间：1月24日开始，3月1日结束。
2. 今日天气：奉贤校区最高气温 4℃，最低气温 -1℃。

【任务指令】：
- 奉贤校区相关问题：必须结合联网搜索到的最新动态（如建筑、美景、学生评价）进行生动介绍。
- 寒假/天气问题：直接引用固定事实，并给出学长学姐式的贴心提醒。
- 回答风格：亲切、幽默、有用，多使用 Emoji。"""

# 初始化 OpenAI 客户端
client = openai.OpenAI(api_key=KIMI_KEY, base_url="https://api.moonshot.cn/v1")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 华理信管小助手服务启动中...")
    logger.info(f"🔑 端口配置: {os.environ.get('PORT', '8080')}")
    yield


app = FastAPI(title="华理信管小助手", lifespan=lifespan)

# 跨域配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


async def search_web(query: str):
    """使用 Tavily 进行联网搜索"""
    if not TAVILY_API_KEY:
        return ""
    try:
        async with httpx.AsyncClient() as http_client:
            url = "https://api.tavily.com/search"
            # 强化搜索词，确保定位到华理奉贤校区
            payload = {
                "api_key": TAVILY_API_KEY,
                "query": f"华东理工大学 奉贤校区 {query} 2026 最新动态",
                "search_depth": "news",
                "max_results": 3
            }
            response = await http_client.post(url, json=payload, timeout=12.0)
            results = response.json().get("results", [])
            return "\n".join([f"信息: {r['content']}" for r in results])
    except Exception as e:
        logger.error(f"⚠️ 联网搜索异常: {e}")
        return ""


async def kimi_stream(question: str):
    """流式生成回答逻辑"""

    # 1. 拦截固定寒假信息（确保绝对精准）
    if any(k in question for k in ["寒假", "放假", "开学"]):
        yield json.dumps({
                             "answer": "同学你好！华理2026年寒假已经定啦：**1月24日至3月1日**。放假虽好，别忘了带走宿舍垃圾和贵重物品哦！✈️"},
                         ensure_ascii=False)
        yield json.dumps({"done": True})
        return

    # 2. 其他问题（如奉贤校区介绍、天气、讲座等）触发联网搜索
    search_info = await search_web(question)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": f"实时搜索参考内容：\n{search_info}" if search_info else "未获取到外部实时信息"},
        {"role": "user", "content": question}
    ]

    try:
        stream = client.chat.completions.create(
            model="moonshot-v1-8k",
            messages=messages,
            stream=True
        )
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield json.dumps({"answer": chunk.choices[0].delta.content}, ensure_ascii=False)

        yield json.dumps({"done": True})
    except Exception as e:
        logger.error(f"❌ Kimi API 调用失败: {e}")
        yield json.dumps({"answer": "哎呀，我的大脑断网了...可以换个姿势再问我一次吗？"}, ensure_ascii=False)
        yield json.dumps({"done": True})


# --- 网页路由 ---
@app.get("/")
async def root():
    return RedirectResponse(url="/chat-ui")


@app.get("/chat")
async def chat(q: str):
    return EventSourceResponse(kimi_stream(q.strip()))


@app.get("/chat-ui", response_class=HTMLResponse)
async def get_ui():
    return HTML_TEMPLATE


# --- 极简响应式前端模板 ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>华理信管小助手</title>
    <style>
        body { font-family: sans-serif; background: #f4f7f9; margin: 0; display: flex; justify-content: center; height: 100vh; }
        .chat-container { width: 100%; max-width: 500px; background: white; display: flex; flex-direction: column; box-shadow: 0 10px 20px rgba(0,0,0,0.1); }
        .header { background: #004ea2; color: white; padding: 18px; text-align: center; font-weight: bold; }
        #box { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 12px; }
        .msg { max-width: 85%; padding: 12px; border-radius: 12px; line-height: 1.5; font-size: 15px; }
        .user { background: #004ea2; color: white; align-self: flex-end; }
        .ai { background: #f0f2f5; align-self: flex-start; }
        .input-area { padding: 15px; border-top: 1px solid #eee; display: flex; gap: 10px; }
        input { flex: 1; padding: 10px; border: 1px solid #ddd; border-radius: 6px; outline: none; }
        button { background: #004ea2; color: white; border: none; padding: 0 20px; border-radius: 6px; cursor: pointer; }
    </style>
</head>
<body>
    <div class="chat-container">
        <div class="header">华理信管小助手 🎓</div>
        <div id="box">
            <div class="msg ai">你好！我是信管小助手。2026年寒假将至，想了解奉贤校区或者最新放假安排吗？</div>
        </div>
        <div class="input-area">
            <input type="text" id="userInput" placeholder="输入问题（如：介绍奉贤校区）" onkeypress="if(event.keyCode==13) send()">
            <button onclick="send()">发送</button>
        </div>
    </div>
    <script>
        const box = document.getElementById('box');
        const input = document.getElementById('userInput');
        async function send() {
            const q = input.value.trim();
            if (!q) return;
            box.innerHTML += `<div class="msg user">${q}</div>`;
            input.value = '';
            box.scrollTop = box.scrollHeight;
            const aiDiv = document.createElement('div');
            aiDiv.className = 'msg ai';
            aiDiv.innerHTML = '正在查询中...';
            box.appendChild(aiDiv);
            const source = new EventSource('/chat?q=' + encodeURIComponent(q));
            let res = '';
            source.onmessage = (e) => {
                const data = JSON.parse(e.data);
                if (data.answer) {
                    if (res === '') aiDiv.innerHTML = '';
                    res += data.answer;
                    aiDiv.innerHTML = res.replace(/\\n/g, '<br>').replace(/\\*\\*(.*?)\\*\\*/g, '<strong>$1</strong>');
                }
                if (data.done) source.close();
                box.scrollTop = box.scrollHeight;
            };
        }
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    # 这一行是解决 Zeabur 502 错误的关键：必须读取环境变量中的 PORT
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"✨ 服务已在端口 {port} 启动")
    uvicorn.run(app, host="0.0.0.0", port=port)
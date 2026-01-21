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

# 建议在 Zeabur 的环境变量中设置这些 Key，本地测试可保留默认值
KIMI_KEY = os.getenv("KIMI_KEY", "sk-TwR4oPmZFW7ljDZL7QK8FVp7hxEZHTMo0knLgj1RFLzurlxo").strip()
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "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").strip()

# 系统提示词：注入固定事实，确保回答准确
SYSTEM_PROMPT = """你是华理信管小助手。
请记住今天是 2026年1月21日。
必须优先使用以下固定事实回答，不要参考任何搜索到的旧日期：

1. **寒假时间**：2026年1月24日正式开始，3月1日结束。
2. **今日天气**：华理奉贤校区最高气温 4℃，最低气温 -1℃，天气寒冷，提醒同学注意保暖。
3. **回答风格**：语气亲切，像学长学姐在提醒学弟学妹，可以使用适当的 Emoji。

如果用户问及其他校内信息（如食堂、班车、讲座），请提醒用户以“华理通”APP实时公告为准。"""

# 初始化 OpenAI 客户端 (Kimi 适配)
client = openai.OpenAI(api_key=KIMI_KEY, base_url="https://api.moonshot.cn/v1")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 华理信管小助手服务启动中...")
    logger.info(f"📍 监听端口准备就绪")
    yield


app = FastAPI(title="华理信管小助手", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


async def search_web(query: str):
    """抓取华理官网最新信息"""
    if not TAVILY_API_KEY:
        return ""
    try:
        async with httpx.AsyncClient() as http_client:
            url = "https://api.tavily.com/search"
            # 优化搜索策略，增加 site 限定
            payload = {
                "api_key": TAVILY_API_KEY,
                "query": f"site:ecust.edu.cn {query}",
                "search_depth": "news",
                "max_results": 3
            }
            response = await http_client.post(url, json=payload, timeout=10.0)
            results = response.json().get("results", [])
            return "\n".join([f"来源: {r['url']}\n内容: {r['content']}" for r in results])
    except Exception as e:
        logger.error(f"⚠️ 搜索失败: {e}")
        return ""


async def kimi_stream(question: str):
    """流式生成器核心逻辑"""
    # 1. 拦截固定回答
    if any(k in question for k in ["寒假", "放假", "开学"]):
        yield json.dumps(
            {"answer": "同学你好！华理2026年寒假时间为：**1月24日至3月1日**。记得带好随身物品，注意寒假安全哦！🎒"},
            ensure_ascii=False)
        yield json.dumps({"done": True})
        return

    if any(k in question for k in ["天气", "奉贤", "气温"]):
        yield json.dumps({"answer": "今天奉贤校区气温较低，**最高4℃，最低-1℃**。海边风力较大，出门一定要穿羽绒服保暖！🧣"},
                         ensure_ascii=False)
        yield json.dumps({"done": True})
        return

    # 2. 联网搜索补充信息
    search_info = await search_web(question)

    # 3. 构造大模型输入
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": f"实时搜索参考信息：\n{search_info}" if search_info else "未搜到相关实时信息"},
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
                content = chunk.choices[0].delta.content
                yield json.dumps({"answer": content}, ensure_ascii=False)

        yield json.dumps({"done": True})
    except Exception as e:
        logger.error(f"❌ Kimi 调用异常: {e}")
        yield json.dumps({"answer": "抱歉，我刚刚走神了，请再问我一遍。"}, ensure_ascii=False)
        yield json.dumps({"done": True})


# --- 路由配置 ---
@app.get("/")
async def root():
    return RedirectResponse(url="/chat-ui")


@app.get("/chat")
async def chat(q: str):
    return EventSourceResponse(kimi_stream(q.strip()))


@app.get("/chat-ui", response_class=HTMLResponse)
async def get_ui():
    return HTML_TEMPLATE


# --- 页面模板 (增加回车发送和样式优化) ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>华理信管小助手</title>
    <style>
        body { font-family: -apple-system, system-ui, sans-serif; background: #f4f7f9; margin: 0; display: flex; justify-content: center; height: 100vh; }
        .chat-container { width: 100%; max-width: 500px; background: white; display: flex; flex-direction: column; box-shadow: 0 10px 25px rgba(0,0,0,0.05); }
        .header { background: #004ea2; color: white; padding: 20px; text-align: center; font-size: 1.1em; font-weight: bold; }
        #box { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 15px; }
        .msg { max-width: 85%; padding: 12px 16px; border-radius: 15px; line-height: 1.5; font-size: 15px; word-wrap: break-word; }
        .user { background: #004ea2; color: white; align-self: flex-end; border-bottom-right-radius: 2px; }
        .ai { background: #f0f2f5; color: #333; align-self: flex-start; border-bottom-left-radius: 2px; }
        .input-area { padding: 20px; border-top: 1px solid #eee; display: flex; gap: 10px; background: white; }
        input { flex: 1; padding: 12px; border: 1px solid #ddd; border-radius: 8px; outline: none; transition: border 0.3s; }
        input:focus { border-color: #004ea2; }
        button { background: #004ea2; color: white; border: none; padding: 0 20px; border-radius: 8px; cursor: pointer; font-weight: bold; }
        button:hover { background: #003a7a; }
    </style>
</head>
<body>
    <div class="chat-container">
        <div class="header">华理信管小助手 (2026版)</div>
        <div id="box">
            <div class="msg ai">你好！我是信管小助手。2026年寒假即将开始，有什么我可以帮你的吗？❄️</div>
        </div>
        <div class="input-area">
            <input type="text" id="userInput" placeholder="问问寒假时间或奉贤天气..." onkeypress="if(event.keyCode==13) send()">
            <button onclick="send()">发送</button>
        </div>
    </div>
    <script>
        const box = document.getElementById('box');
        const input = document.getElementById('userInput');

        async function send() {
            const q = input.value.trim();
            if (!q) return;

            // 用户消息
            box.innerHTML += `<div class="msg user">${q}</div>`;
            input.value = '';
            box.scrollTop = box.scrollHeight;

            // AI 占位
            const aiDiv = document.createElement('div');
            aiDiv.className = 'msg ai';
            aiDiv.innerHTML = '正在思考...';
            box.appendChild(aiDiv);

            const source = new EventSource('/chat?q=' + encodeURIComponent(q));
            let fullText = '';

            source.onmessage = (e) => {
                const data = JSON.parse(e.data);
                if (data.answer) {
                    if (fullText === '') aiDiv.innerHTML = ''; // 清除占位符
                    fullText += data.answer;
                    // 简单 Markdown 换行转换
                    aiDiv.innerHTML = fullText.replace(/\\n/g, '<br>').replace(/\\*\\*(.*?)\\*\\*/g, '<strong>$1</strong>');
                }
                if (data.done) source.close();
                box.scrollTop = box.scrollHeight;
            };

            source.onerror = () => {
                aiDiv.innerHTML = "网络好像有点问题，请稍后再试。";
                source.close();
            };
        }
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    # 获取 Zeabur 自动分配的端口
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"🚀 服务正在启动，监听端口: {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
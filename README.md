 🎙 Interview Copilot (AI 智能面试辅助工作台)

 📖 项目简介

Interview Copilot 是一款专为技术求职者打造的、完全本地化运行的高性能 AI 面试辅助系统。

在真实的面试场景中，候选人往往因为紧张而遗忘项目细节，或因面试官语速过快而抓不住核心问题。本项目通过底层的双通道音频分离技术，结合极低延迟的本地离线语音识别，将面试官的声音实时转化为文本，并借助 DeepSeek 大模型的强大推理能力，在局域网内的手机端秒级呈现具有个人特色的口语化建议答案。系统同时内置了“面试策略卡”与本地知识库，形成从“面试准备”到“实战辅助”再到“面试复盘”的完美闭环。

 ✨ 核心特性

- 🎧 双通道物理隔离采集：自动分离系统回环音频（面试官）与麦克风音频（你），互不干扰，从根源上解决重叠说话导致的识别混乱。
- ⚡ 工业级低延迟断句：放弃传统的固定时长静音检测，采用 Silero VAD 神经网络模型，精准区分人声与背景噪音，断句灵敏且极低延迟。
- 🗣️ Two-Pass 离线语音识别：集成 `sherpa-onnx` 引擎与 Paraformer 离线模型，深度优化中英混合与计算机技术黑话（如 Docker、Redis、K8s），准确率碾压通用模型。
- 🛡️ CAM++ 声纹过滤：面试前支持声纹注册，面试中实时比对。有效过滤外放时的回声与旁人干扰，只认“你”的声音。
- 🧠 父子策略卡系统：纯文本 Markdown 存储的专属面试话术库。父策略约束底线（如“不编造”），子策略按关键词动态注入（如“强调我主动发起的重构”）。支持在与 AI 讨论时自动生成并保存。
- 📚 个人知识库 RAG：支持上传简历、项目文档（PDF/DOCX/TXT），自动切分向量化（ChromaDB）。面试时根据问题精准检索本地素材，让 AI 的回答充满你的真实细节。
- 📱 局域网多端协同：电脑端提供完整的 pywebview 工作台，手机端通过扫码连接局域网，答案以极低延迟流式推送到手机上。
- 🔒 极致的隐私与合规：所有音频处理、语音识别、向量检索均在你的本地电脑上完成，仅生成文本与最终大模型的对话走云端接口，录音文件绝不外流。

 🛠️ 技术架构与栈

- 核心框架: Python 3.10+, FastAPI, Uvicorn, WebSockets
- 前端界面: HTML5, 原生 JavaScript, CSS3 (基于 pywebview 渲染)
- 语音处理: `sounddevice`, `pyaudiowpatch` (Windows 回环), `scipy` (重采样)
- AI/推理引擎: `sherpa-onnx` (VAD + ASR), `SpeechBrain` / `PyTorch` (CAM++ 声纹)
- 大语言模型: DeepSeek API (兼容 OpenAI SDK)
- 向量数据库: ChromaDB, `SentenceTransformers` (bge-small-zh-v1.5)

 📂 核心目录结构

```text
interview-copilot/
├── backend/                  后端核心代码
│   ├── asr/                  语音识别 (VAD + 离线模型)
│   ├── audio/                双通道音频采集与重采样
│   ├── logic/                核心逻辑 (大模型调用、策略卡、Prompt)
│   ├── rag/                  向量库与文件解析
│   ├── speaker/              声纹注册与验证
│   ├── storage/              SQLite 历史记录
│   └── main.py               FastAPI 主入口 (全异步并发)
├── web/
│   ├── desktop/              电脑端工作台网页
│   └── mobile/               手机端提词器网页
├── data/                     (运行时生成) 核心数据目录
│   ├── models/               依赖的本地模型目录
│   ├── strategy/             策略卡 Markdown 文件
│   ├── uploads/              知识库原文件
│   ├── chroma_db/            向量数据库持久化
│   ├── config.json           API Key 与设备配置
│   └── history.db            历史会话记录
├── launcher.py               桌面端启动器 (pywebview 窗口)
├── download_models.py        一键模型下载脚本
├── config.example.json       配置模板
└── requirements.txt          项目依赖清单
```

🚀 快速开始 (源码部署指南)
1. 环境准备
强烈建议使用 Python 3.10 或 3.11 环境运行本程序。请确保你的电脑安装了 Python 并配置了环境变量。

bash
 进入项目根目录后，安装所有 Python 依赖
pip install -r requirements.txt
2. 下载本地模型 (必做)
本项目强依赖 VAD、离线语音识别与声纹识别模型（总计约 2.5GB）。请在项目根目录执行以下命令：

bash
python download_models.py
注：脚本已内置国内网络加速（HuggingFace 镜像），会自动下载所需模型并解压至 data/models/ 目录。下载时长视网络状况而定。

3. 配置文件初始化
确保项目根目录下存在 data/ 文件夹（如果没有，脚本会自动创建）。

复制根目录的 config.example.json，重命名为 data/config.json。

打开 data/config.json，填入你的 DeepSeek API Key：

json
{
  "deepseek": {
    "api_key": "sk-你的真实API_KEY填在这里",
    "base_url": "https://api.deepseek.com"
  }
}
4. 启动后端服务
方式一：命令行启动

bash
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
方式二：带界面的启动器

bash
python launcher.py

5. 访问工作台
启动成功后，打开浏览器访问：http://localhost:8000/desktop，或者直接使用 launcher.py 弹出的独立窗口。在设置中配置好麦克风和系统回环设备，即可开始模拟面试或实战。

📦 免安装包下载 (Releases)
如果你不想配置 Python 环境，请前往本仓库的 Releases 页面，下载最新的 InterviewCopilot_v1.0.0.7z 压缩包。

使用 7-Zip 解压到任意纯英文路径下。

重要：打开解压后的 data/config.json，填入你的 DeepSeek API Key。

双击 InterviewCopilot.exe 即可直接运行（自带独立窗口）。

❓ 常见问题排错 (FAQ)：

启动后报错找不到音频设备？
请进入设置面板，手动选择你的“麦克风”和“系统回环”设备。回环设备通常带有 [Loopback] 标识。

AI 不回答，或者报 401 Authentication 错误？
请检查 data/config.json 中的 api_key 是否填写正确，以及账号是否有可用余额。

面中遇到断句太碎或识别不出？
检查麦克风音量（RMS）是否过小，或在设置面板调整 VAD 的静音判定时长（默认 0.5 秒）。

WinError 126 或 torch_cpu.dll 找不到？
源码运行请确保执行了 pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu 安装纯 CPU 版。如果使用 Releases 的压缩包则不会出现此问题。

⚠️ 免责声明与合规提醒
隐私与合规：本系统包含录音、声纹提取与文本处理功能。请确保在获得对方明确同意的前提下使用本工具，严格遵守所在地区法律法规（如《个人信息保护法》）。

使用场景：许多公司明确禁止在真实面试中使用 AI 辅助。本工具仅供模拟面试、面试复盘、演讲提词及无障碍辅助学习使用。 请勿将其用于任何违反考场纪律、面试规则的作弊行为。

免责：因使用本工具导致的面试取消资格、账户封禁、法律纠纷等一切后果，由使用者自行承担。作者不对任何间接或直接损失负责。

Built with ❤️ by junmohan
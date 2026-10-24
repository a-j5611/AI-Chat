# AI Chat

**本地 Ollama 对话客户端** —— 多轮对话、识图、联网搜索、会话管理，Windows 11 风格界面。

> 由原 DeepSeek Controller 更名而来；首次启动会自动把旧配置与会话迁移到 `%APPDATA%\AIChat`。

## 本次更新

| 项目 | 说明 |
|---|---|
| **更名** | DeepSeek Controller → **AI Chat**（配置目录 `%APPDATA%\AIChat`，旧配置自动迁移） |
| **界面** | 改用 **Windows 11 / WinUI 配色**（浅色 `#F3F3F3`/`#FFFFFF`/`#0067C0`，深色 `#202020`/`#2B2B2B`/`#60CDFF`）；卡片 8px 圆角 + 1px 描边；按钮边缘**柔化**（密集圆弧 + 混色过渡环）；字体统一**微软雅黑** |
| **主题** | 新增「跟随系统」（读 `AppsUseLightTheme`），与 Windows 深浅色同步 |
| **强调色** | 设置页可选 **8 个 Win11 强调色** + 「跟随 Windows」（读 DWM `ColorizationColor` 并吸附最近预设），按钮/选中项/徽章整体换色 |
| **搜索·更快** | 多引擎**并发竞速**（原来 5 个引擎串行、各 15s，最坏 75s）；实测单查询 **1.4–1.6 秒**；结果缓存 10 分钟（重复查询 ~0ms） |
| **搜索·更多** | 每查询结果 5→**10 条**，合并上限 48，子查询 4→5；技术类问题实测 5 查询 **45 条 / 4.2 秒** |
| **搜索·更准** | **不检索字词释义**：词典/释义站点（汉典、百度汉语、有道、iciba、wiktionary、dictionary.com…）与"X是什么意思"类页面会被剔除；纯查词问题（且非专业术语）**直接跳过联网**交给模型。**专业术语不受此限**（含拉丁字母/缩写或命中技术词表时照常检索） |

## 界面：Windows 11 风格

* 配色与 WinUI 设计令牌一致（见上表），支持「跟随系统」深浅色；
* 强调色 8 色可选，并可按 Windows 的强调色自动吸附；
* 按钮 4~6px 圆角，边缘用「密集圆弧 + 混色过渡环」柔化，悬停/按下各有色阶；
* 窗口通过 DWM 开启 Win11 圆角、深色标题栏，标题栏颜色跟随主题；
* 字体统一「微软雅黑」（含菜单、ttk、对话框等 Tk 命名字体）。

（本项目由DeepSeek-V41-Flash生成）

# DeepSeek Controller

本地 Ollama / DeepSeek-R1 图形化控制程序 —— 中英双语、浅色深色主题、可切换图片背景。

Local Ollama / DeepSeek-R1 GUI controller with bilingual UI, light/dark themes and switchable image backgrounds.

\---

## 功能

|模块|说明|
|-|-|
|**对话**|流式输出、R1 思考过程折叠展开、多轮上下文、停止生成、每轮 token 速度统计、一键复制、**导出 Markdown**|
|**对话记录**|左侧会话列表（类似 DeepSeek Harness）：**每次对话自动保存**、按首条提问自动生成标题；点击即载入并完整还原思考过程与参考来源；支持新建 / 重命名（右键）/ 删除；重启后自动恢复上次会话|
|**联网搜索**|对话工具栏**三态切换：关 / 快 / 深**。快=单查询；**深=问题自动拆成多组检索词 × 多引擎（Bing/360/搜狗）并发检索，合并去重后批量抓正文**，资料上限可设**不限**，需要时**自动提升上下文**；回答标注 [1][2] 来源，附可点击来源列表与「查看资料」原文窗；无需 API Key|
|**模型**|列出本地模型（体积/量化/修改时间）、设为当前模型、**完全删除（含数据文件，有详细提示）**、输入名称在线拉取（带实时进度条）、**「添加模型」打开在线模型库**、**清理未使用数据**|
|**识图**|对话中附加图片（文件选择或 Ctrl+V 粘贴剪贴板），自动缩放到合适尺寸后交给视觉模型识别；当前模型不支持识图时会**检测并推荐视觉模型，一键下载并自动切换**；图片随会话保存与还原|
|**模型库**|自动获取 ollama.com 模型列表、关键词搜索、查看某模型的全部可用版本与**精确体积**、一键下载（进度 + 实时速度），已下载版本自动标记为「已下载」|
|**下载续传**|下载中断（关程序/断网）后**分片保留**，模型页出现「发现未完成的下载」横幅，点**继续下载**即断点续传；也可一键**删除残留**回收空间。失败**不会**被误判为成功|
|**服务**|状态灯实时监测、启动 / 停止 / 重启 Ollama 服务、接口地址与版本、程序/模型目录、模型占用磁盘、相关进程内存与 CPU|
|**设置**|浅色/深色主题、中文/English 切换、**背景图片（自动铺满 + 高斯模糊可调 + 压暗可调）**、内置渐变、背景库、生成参数（温度 / top\_p / 线程数 / 上下文 / 最大生成长度）|
|**日志**|应用事件日志与服务端日志，可复制、可清空|

## 运行

双击 **`启动 DeepSeek Controller.bat`**，或：

```powershell
pythonw DeepSeekController.pyw
```

启动器会自动挑选可用的 Python：优先使用自带 tkinter + Pillow 的运行时，其次使用 PATH 中的 `pythonw`/`python`。

**依赖**：Python 3.10+，标准库 tkinter（必需）；Pillow（可选，仅背景图片与缩略图需要；缺失时内置渐变仍可用）。

## 界面操作

* 左侧导航切换五个页面；顶栏可一键切换主题、语言、跳转背景设置。
* 对话输入框：`Enter` 发送，`Shift+Enter` 换行。
* 生成过程中「发送」按钮变为「停止」，可随时中断。
* **对话记录**：左侧列表点标题即载入该会话；`＋` 新建；右键标题重命名；`✕` 删除。
  当前会话会以高亮标出，对话内容在发送后与回答结束后自动落盘，退出程序前再存一次。
* **联网搜索**：点对话页右上角「联网搜索 · 关」切换为「开」，之后每次提问都会先检索再回答；
  回答下方的「◈ 参考来源 · N」可展开，点标题即在浏览器打开。

## 下载中断与续传

下载（视觉模型、模型库、手动拉取）中途关闭程序或断网时：

1. **分片文件会保留**在 `<模型目录>/blobs/*-partial*`，不会作废；
2. 程序会把未下完的模型名记进配置（`download.pending_model`）；
3. 下次打开**模型页**会出现横幅：「发现未完成的下载：N 个分片，约 X　上次未下完：名称」；
4. 点 **继续下载** 从断点续传（实测中断在 15%，续传起点即 15%，而非从 0 重来）；
5. 若确认不需要了，点 **删除残留** 回收空间（会提示将释放多少）。

失败处理：下载异常**不会**被当作成功，且**成功后会核实**（查 `/api/tags` 确认模型真的装上了，
否则报失败）；失败时显示原因并给出 **重试 / 取消下载**，重试同样是断点续传。

### 已修复的三个真实缺陷（均实测复现）

| 缺陷 | 后果 | 修复 |
|---|---|---|
| worker 在 `finally` 里无条件上报完成 | 失败也被判为成功，自动切到一个**并未安装**的模型 | 只有正常跑完才算完成；并要求「成功即核实」，查 `/api/tags` 确认已安装 |
| 速度用「累计字节 ÷ 总耗时」 | 那是**平均速度**，与任务栏实时速率对不上；**续传时更会虚高**（累计字节含上次数据） | 改为按采样增量算的**当前速率**（指数平滑），实测平均误差 0.86 MB/s，旧算法 2.73 MB/s |
| 失败后进度条自动消失、无续传入口 | 想继续只能重走整个流程 | 失败时保留进度条并给 **重试 / 取消**；模型页横幅给 **继续下载 / 删除残留** |

### Ollama 0.35 的两种卡死状态与应对

实测这台机器上 `gemma3:4b`（3.11 GB，16 分块）出现过两种异常：

1. **最后一块极慢**：前 15 块以 10 MB/s 完成，最后一块掉到 **250 KB/s**，看起来像"卡在 97% 不动"。
   程序在**超过 3 分钟无任何字节进展**时会提示「下载停滞」，并始终显示**当前速度**（而不是容易被误读的平均值）。
2. **分块账本损坏**：中断后重试时 Ollama 会认为所有分块都已完成而跳过下载，但实际数据不完整 →
   封盘哈希校验失败 → **既不报错也不重下，永久卡住**（分片还被服务端句柄锁住，普通删除会失败）。
   应对：模型页横幅的 **清理并重下** —— 自动**停服务 → 删损坏分片 → 起服务 → 重新下载**，一键脱离死锁。

> 判断下载是否真完成的正确方法：`fsutil file queryvaliddata` **不可用**——Ollama 用
> `SetFileValidData` 预分配，该值一开始就等于文件大小；进度要看 `blobs/*-partial-*/` 里各分块的
> `Completed`，最终完整性要看正式 blob 的 sha256 是否等于其文件名中的摘要。

## 完全删除与磁盘清理

Ollama 的 `DELETE /api/delete` **只删清单**，blob 数据会留在磁盘上（要等下次服务启动才可能回收）。
本程序按磁盘结构精确清理：

* **定位方式**：清单文件的 SHA256 与 `/api/tags` 返回的 digest 一致，据此找到目标模型对应的清单，
  再取出它引用的全部 blob。
* **共享保护**：同一底模的不同变体会共用 blob（例如 `deepseek-r1:8b` 与 `deepseek-r1:8b-tuned`
  共用 4.87 GB 的权重）。删除前会计算「被其他模型引用」的集合，**只清理无人引用的文件**，
  提示框里会写明「将释放多少 / 多少为共享保留」。
* **清理未使用数据**：扫描 `blobs/`，删除没有任何清单引用的文件（处理误删模型后的残留）。
  为安全起见会跳过 `-partial` 分片与 10 分钟内新增的文件，避免影响正在进行的拉取。

这两个操作都带详细确认框，删除后在提示与日志里报告实际释放的空间。

## 识图

1. 点输入框右侧 **「图片」** 选择文件，或在输入框按 **Ctrl+V** 粘贴剪贴板图片（最多 3 张，可逐张移除）。
2. 发送前会检查当前模型是否具备 `vision` 能力（读 `/api/show` 的 `capabilities`）：
   * 支持识图 → 直接发送；
   * 本地已装其它视觉模型 → 自动切换过去并提示；
   * 都没有 → 弹出引导，可选 **qwen3-vl:2b（1.8 GB，最快）/ qwen2.5vl:3b（3.0 GB）/ gemma3:4b（3.1 GB）**，
     一键下载并在完成后自动切换。
3. 图片会自动处理：长边压到 1024 px 再发模型（CPU 上视觉编码很吃尺寸），
   会话里另存 640 px 版本与 200 px 缩略图，避免记录文件过大。
4. 多轮对话只给**最后一条**用户消息带图片，历史图片不重复发送，避免 prompt 与耗时膨胀。

## 联网搜索（快 / 深）

对话工具栏的「联网搜索」按钮三态循环：**关 → 快 → 深**。

```
快速模式
提问 ──> 单次检索（Bing，0.3~0.5s）
      ──> 抓取前 N 篇正文（可选）
      ──> 注入 system 消息 ──> 流式作答，标注 [1][2]

深度模式
提问 ──> 启发式拆词（毫秒级，5 组不同角度检索词）
      ──> 多引擎并发检索（Bing / 360 / 搜狗），合并去重
      ──> 批量抓取网页正文（并发 8 路，自动跳过 JS 页与慢站点）
      ──> 按配置上限注入（可设“不限”）+ 需要时自动提升 num_ctx
      ──> 流式作答；气泡内可展开来源，点「查看资料」看注入原文
```

* 数据源全部是公开搜索页，**不需要 API Key**；`websearch.py` 按 `bing → bing_html → so360 → sogou → baidu` 自动回退。百度现已常态返回「安全验证」页，故排在最后。
* **实测对比**（同一问题，本机纯 CPU）：

  | | 传统单查询 | 深度检索 |
  |---|---|---|
  | 检索词 | 1 组 | 5 组 |
  | 原始结果 | 5 条 | **75 条 → 去重 34 条** |
  | 网页正文 | 0 篇（仅摘要） | **10 篇** |
  | 注入资料 | 2000 字上限 | **16717 字（约 5370 token），不限** |
  | 检索耗时 | 0.5s | **3.7s** |

* 真正的耗时在 CPU 处理长 prompt（约 40 token/s）：5370 token ≈ 2 分钟。设置页会实时显示
  「预计约 X 千字 ≈ Y token，CPU 处理约需 Z 秒」，可按需在**快**与**深**之间切换。
* 「自动提升上下文」会在资料超过当前 `num_ctx` 时自动上调（上限可配，默认 16384），避免资料被悄悄截断。
* 抓取失败/无结果时退回纯模型知识作答并给出提示，不会中断对话。
* 设置页可调：检索模式、检索词数量、结果条数（3~30）、抓取正文页数（0~20）、每篇字数（0~2000+）、资料上限（0=不限）、是否合并多引擎、是否自动提升上下文，并有一键「测试搜索」。
* 思考过程默认折叠，点击「◆ 思考过程 · 展开」查看。
* **模型 → 添加模型**：打开模型库，搜索并选择版本下载；下载完成后会自动刷新本地模型列表。

### 模型库的数据来源

|用途|接口|
|-|-|
|模型列表|`https://ollama.com/search?q=<关键词>`|
|可用版本|`https://ollama.com/library/<模型>/tags`|
|精确体积|`https://registry.ollama.ai/v2/library/<模型>/manifests/<版本>`（累加各层大小）|

网络不可用时会回退到内置的常用模型列表（deepseek-r1 / qwen3 / llama3.2 / gemma3 / phi4 等），下载仍走本机 Ollama，不受影响。

## 配置文件

```
%APPDATA%\DeepSeekController\config.json            主题、语言、背景库、参数、窗口、上次会话
%APPDATA%\DeepSeekController\sessions\*.json        每段对话的完整消息（含思考过程与来源）
%APPDATA%\DeepSeekController\sessions\index.json    会话列表索引（标题 / 时间 / 条数）
%APPDATA%\DeepSeekController\error.log              启动异常与界面回调异常堆栈
```

背景库最多保留 12 张图片，点击缩略图即可切换；「从背景库移除」只删除记录，不动原图。
会话按最近 200 段保留，超出的旧会话会自动清理。

## 目录结构

```
DeepSeekController/
├── DeepSeekController.pyw        入口（DPI 感知 + 异常兜底）
├── 启动 DeepSeek Controller.bat  启动器
└── app/
    ├── main\_window.py   窗口外壳：背景画布、圆角卡片、侧栏、顶栏、状态轮询
    ├── chat\_view.py     对话视图与消息气泡
    ├── gallery.py       模型库：在线列表 / 版本体积 / 下载
    ├── websearch.py     联网搜索：多引擎检索 / 正文抽取 / 上下文拼装
    ├── sessions.py      对话记录：本地保存 / 列表 / 载入 / 重命名 / 删除
    ├── panels.py        模型 / 服务 / 设置 / 日志 四个面板
    ├── widgets.py       自绘组件：圆角按钮、分段控件、开关、滑条、进度条、弹窗
    ├── backgrounds.py   背景渲染：渐变、铺满裁剪、模糊、压暗、缩略图
    ├── ollama\_api.py    Ollama HTTP 客户端 + 服务进程管理（ctypes 读内存/CPU）
    ├── theme.py         浅色/深色调色板、字体、跨主题颜色迁移
    ├── i18n.py          中英文案
    └── config.py        配置读写
```

## 与本机 Ollama 的配合

程序默认按以下约定工作（可在设置里查看，配置文件里可改）：

* 接口：`http://127.0.0.1:11434`
* 程序目录：`D:\\Ollama`（`ollama.exe`）
* 模型目录：`D:\\Ollama\\models`

点击「重启服务」时，程序会用 `OLLAMA\_MODELS=D:\\Ollama\\models`、`OLLAMA\_IGPU\_ENABLE=0` 启动 `ollama serve`。

> 本机实测：i7-12700H 上 `deepseek-r1:8b`（Q4\_K\_M）CPU 推理约 \*\*9.2 tok/s\*\*（`num\_thread=14` 最优）；
> 16 GB 内存跑 CPU 推理需约 8.6 GB 空闲内存，若出现 `out-of-memory`，
> 可把 `OLLAMA\_IGPU\_ENABLE` 设为 `1` 改用核显（Vulkan，约 8.0 tok/s，内存占用更低）。

## 常见问题

|现象|处理|
|-|-|
|顶栏显示「服务离线」|到「服务」页点「启动服务」，或双击 `D:\\Ollama\\restart-ollama.cmd`|
|发送提示「请先选择模型」|到「模型」页点某个模型的「使用」|
|生成报 `out-of-memory`|关闭占内存的程序，或改用核显（见上）|
|背景图片按钮不可用|缺少 Pillow：`pip install pillow`|
|启动无反应|查看 `%APPDATA%\DeepSeekController\error.log`（界面回调的异常也会记录在这里，并弹提示）|
|点按钮没反应|同上：异常信息会显示为应用内提示并写入 error.log|
|对话报 404|配置里的模型已被删除；程序会自动切到可用的模型，也可到「模型」页手动选择|

\---

## English summary

A tkinter desktop app to control a local Ollama server and chat with DeepSeek-R1.
**Chat** (streaming, collapsible reasoning, Markdown export), **Web search** (Bing / 360 / Baidu with automatic
fallback, no API key; results are injected as context and cited as [1][2], with a clickable source list),
**Models** (list / use / delete / pull with progress,
plus an online **Model gallery** with search, per-version sizes and one-click download),
**Service** (start / stop / restart + live status, process memory \& CPU), **Settings** (light/dark theme,
中文/English, background image with adjustable blur \& dim, built-in gradients, background library,
generation parameters), **Logs** (app events + server log).

Run `启动 DeepSeek Controller.bat` or `pythonw DeepSeekController.pyw`.
Requires Python 3.10+ with tkinter; Pillow optional (image backgrounds only).
Config: `%APPDATA%\\DeepSeekController\\config.json`.


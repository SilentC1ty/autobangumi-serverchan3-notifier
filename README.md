# Server酱³ 通知模板

**新一集下载完成后，通过 Server酱³ 发送带海报、番剧名、季度和集数的自定义 Markdown 通知。**

版本：0.2.0。目标环境：AutoBangumi 4.0.0、Python 3.14+、ab_sdk 0.6.0。清单 SDK 范围为 `>=0.5,<1`，实际测试基线为 0.6.0。

## 实现方式

参考 AB 内置 Server Chan 的发送行为，通过官方 `notifier` 扩展点增加独立的 **`server3-template`** 渠道。宿主在下载完成、整理并产生普通新集数通知后，把 `NotificationMessage(kind="episode")` 交给插件，插件渲染模板并发送到 Server酱³。

不修改 AB 源码，不替换内置渠道，不 import `module.*`，不 Monkey Patch，不监听下载或整理事件，不查询 TMDB/BGM。触发时机、集数识别、通知去重和海报数据继续由 AB 管理。

0.1.0 的系统事件模板功能保留：`message_template` 钩子处理内置 `server-chan`、兼容别名 `serverchan` 以及新渠道 `server3-template` 的系统事件。Telegram、Bark、Discord、Webhook、Gotify、Pushover、企业微信等其他渠道不受影响。

## 安装与启用

从 [GitHub 仓库](https://github.com/SilentC1ty/autobangumi-serverchan3-notifier) 的 **Code → Download ZIP** 下载源码，解压后把根目录中的 `plugin.toml`、`README.md` 和整个 `server3_template` 目录复制到下方位置。安装目录名必须为 `server3-template`，与 GitHub 仓库名不同。

如果已使用开发命令打包，也可将生成的 `dist/server3-template-0.2.0.zip` 解压到同一位置。安装包不随源码提交，需要运行 `uv run ab-plugin pack .` 生成。保证不多套一层文件夹：

```text
/app/config/plugins/local/server3-template/
├── plugin.toml
├── README.md
└── server3_template/
    ├── __init__.py
    ├── notifier.py
    └── templates.py
```

群晖宿主机挂载目录示例：

```text
/volume2/docker/AutoBangumi/config/plugins/local/server3-template/
```

1. 复制或升级插件目录后重启 AutoBangumi。
2. 设置 → 插件 → 允许未签名插件 → 启用“Server酱³ 通知模板”。
3. 在插件设置中填写 **Server酱³ SendKey**，格式为 `sctp<uid>t<key>`。
4. 设置 → 通知 → 开启通知 → 添加渠道 → 类型选择 **`server3-template`**，并启用该渠道。
5. 使用新渠道的测试按钮检查 SendKey 与新集数文字模板；测试消息不伪造海报，真实海报需要实际新集数消息。

**仅升级插件、继续使用内置 `server-chan` 渠道，不会启用新的新集数模板。必须添加 `server3-template` 渠道。**

如果原来的内置 Server Chan 与新渠道使用同一 SendKey，可停用原渠道以免收到两份通知。其他通知渠道可继续保留。本插件不会自动迁移、停用或修改任何现有渠道。

SendKey 使用 SDK `secret_field` 声明，宿主设置页显示密码框，读取 API 由宿主掩码。新渠道只接收 Server酱³ 的 `sctp...` SendKey，不接收 Turbo 的 `SCT...` SendKey。插件不会从内置渠道偷偷读取凭据。

## 海报如何显示

在 **设置 → 通知** 配置 `base_url`，例如：

```text
https://ab.example.com
```

AB 把已有海报路径拼接为 `poster_url`，交给官方通知接口。本插件使用 Markdown 图片语法把地址插入正文，不读取本地图片、不额外查询番剧信息、不下载或上传海报。

- 图片地址需要能被查看 Server酱³ 消息的客户端访问；推荐使用 HTTPS。仅容器内或仅宿主机可达的地址，手机未必能访问。
- 番剧没有海报、未配置 `base_url` 或 URL 无效时，`{{ poster }}` 为空，文字通知仍正常发送。
- **海报显示在 Server酱³ APP 打开的 Markdown 正文中，不保证出现在手机锁屏横幅或消息列表卡片中。** 卡片摘要使用本次通知标题，避免把 Markdown 原文作为摘要。
- 自定义正文中使用 `{{ poster }}` 最方便；也可自行写 `![封面]({{ poster_url }})`，但后一种写法在没有海报时会留下空图片标记。

## 配置项

| 配置项 | 用途 | 默认值 |
| --- | --- | --- |
| `enabled` | 启用增强发送与系统事件模板 | `true` |
| `sendkey` | 新渠道使用的 Server酱³ 密钥 | 空，需填写 |
| `episode_title_template` | 新集数标题 | `{{ title }} 第{{ season }}季 第{{ episode }}集下载完成` |
| `episode_body_template` | 新集数 Markdown 正文 | 海报、番剧名、季度、集数、事件说明 |
| `title_template` | 系统事件标题，兼容 0.1.0 | `{{ default_title }}` |
| `body_template` | 系统事件 Markdown 正文，兼容 0.1.0 | `{{ default_body }}` |

官方配置表单目前只公开普通字符串字段，没有文档化的 textarea metadata。模板本身保留换行；需要输入多行 Markdown 时，可停止 AB 后合并修改 `config.json`，再重新启动。不要覆盖其他现有配置。宿主另有 `plugins.enabled` 开关。

插件自己的新集数正文模板优先使用；渠道条目原有的 `template` 渲染结果可通过 `{{ default_body }}` 引用。

## 新集数变量与 Markdown 示例

| 变量 | 含义 |
| --- | --- |
| `{{ title }}` / `{{ official_title }}` | 番剧名；缺少 official_title 时使用宿主标题 |
| `{{ season }}` | 季度数字，如 `2` |
| `{{ episode }}` | 集数数字，如 `5` 或特别篇 `5.5` |
| `{{ poster }}` | 完整 Markdown 海报图片，无海报时为空 |
| `{{ poster_url }}` | 海报 URL，无海报时为空 |
| `{{ event }}` | SDK 消息类型，新集数为 `episode` |
| `{{ event_name }}` | 新集数的中文说明：`新集数下载完成` |
| `{{ default_title }}` | 宿主原始通知标题 |
| `{{ default_body }}` | 宿主原始通知正文，可包含渠道原有模板的结果 |

标题示例：

```text
✅ {{ title }} S{{ season }}E{{ episode }} 下载完成
```

Markdown 正文示例：

```markdown
{{ poster }}

## {{ title }}

| 项目 | 内容 |
| --- | --- |
| 季度 | 第 {{ season }} 季 |
| 集数 | 第 {{ episode }} 集 |
| 状态 | {{ event_name }} |

> 可以开始观看啦。
```

Markdown 由 Server酱³ 客户端渲染，插件只做文本替换，不改变你编写的 Markdown。番剧字段也按原始文本插入，不额外进行 Markdown 转义。

### JSON 配置示例

以下是需合并到现有配置中的结构示例。替换示例 SendKey 和 `base_url`，保留你原有的其他通知渠道：

```json
{
  "notification": {
    "enable": true,
    "base_url": "https://ab.example.com",
    "providers": [
      {"type": "server3-template", "enabled": true}
    ]
  },
  "plugins": {
    "allow_unsigned": true,
    "enabled": {"server3-template": true},
    "options": {
      "server3-template": {
        "enabled": true,
        "sendkey": "sctp123tREPLACE_WITH_REAL_KEY",
        "episode_title_template": "✅ {{ title }} S{{ season }}E{{ episode }} 下载完成",
        "episode_body_template": "{{ poster }}\n\n## {{ title }}\n\n- 季度：第 {{ season }} 季\n- 集数：第 {{ episode }} 集\n- 状态：{{ event_name }}\n\n> 可以开始观看啦。",
        "title_template": "{{ default_title }}",
        "body_template": "事件：{{ event }}\n级别：{{ severity }}\n\n{{ default_body }}"
      }
    }
  }
}
```

JSON 中的 `\n` 表示真正的换行；WebUI 中支持粘贴多行的输入位置则直接使用实际换行。

## 系统事件变量

`title_template`、`body_template` 用于系统事件，所有事件共用这组模板：

| 变量 | 含义 |
| --- | --- |
| `{{ default_title }}` / `{{ default_body }}` | 钩子收到的标题、正文；可能已被更早的模板插件处理 |
| `{{ event }}` | 具体事件类型，如 `download_failure`、`rss_failure` |
| `{{ severity }}` | 事件严重程度；缺失或为 None 时为空 |

自动暴露 dataclass 公开字段及 `event.payload()`，例如下载添加失败的 `official_title`、`torrent_name`，RSS 异常的 `rss_name`、`rss_url`、`error`，下载器不可用的 `host`、`reason`、`instance_id`，重命名冲突的 `target_path` 等。

支持 SDK 已有及未来的系统事件，不硬编码事件清单。新集数变量不能凭空用于系统事件：例如系统事件没有海报数据时，`{{ poster }}` 仍是未知变量。

## 替换规则与容错

- 只支持 `{{ variable }}`，变量名匹配 `[A-Za-z_][A-Za-z0-9_]*`，变量两侧可留空白。
- 未知变量及 None 替换为空字符串；零、False 和小数按正常文本输出。
- 单次替换，不递归解析变量值，不执行 Python、属性访问、Jinja2、if、for 或过滤器。不支持的表达式和未闭合占位符保留原样。
- 系统事件中 payload 优先于同名 dataclass 字段，但不能覆盖四个通用变量；私有字段及非字符串键不暴露。
- 系统事件数据或模板异常：钩子返回 None，宿主继续使用原文案。
- 新集数模板异常：标题、正文整体回退到宿主原文案，再尝试发送，不输出半成品。
- 空的新集数标题回退到宿主标题；没有海报只丢图片，不影响文字。
- 网络异常、HTTP 拒绝、JSON 异常或服务业务错误返回 False，不抛普通运行异常；不会自动重试或改用内置渠道，以免重复通知。
- HTTP 成功且官方返回整数 `code == 0` 才算成功。API 地址从有效的 `sctp<uid>t<key>` 生成，请求有 10 秒超时，不跟随重定向。
- 插件错误日志使用中文，不输出异常原文、SendKey、请求地址或完整通知数据。

## 0.1.0 升级说明与限制

原来的 `enabled`、`title_template`、`body_template` 不改名，原有系统事件配置可继续使用。新字段都有默认值，因此升级本身不会要求重新配置旧功能。

要实现带海报的新集数通知，须额外填写插件 SendKey、添加 `server3-template` 渠道，并为海报配置 AB 的 `notification.base_url`。本插件不能让原有 `message_template` 钩子处理普通新集数，0.2.0 是通过官方 notifier 获取新集数数据的。

新集数默认模板共用一组，不按番剧分别配置；系统事件也共用一组。发送时机、失败重发与历史消息补发不由本插件接管。站内通知中心不受修改。

## 开发与验证

SDK 来自 [AutoBangumi 4.0.0 Release](https://github.com/EstrellaXD/Auto_Bangumi/releases/tag/4.0.0)，不发布到 PyPI。项目已在 uv 配置中固定官方 0.6.0 wheel 的 URL；HTTP 使用 SDK 和宿主已有的 httpx2，不增加第三方模板引擎或 Server酱 SDK。

```bash
uv run --python 3.14 pytest -p no:cacheprovider
uv run ab-plugin validate .
uv run ab-plugin pack .
```

所有测试通过真实 `ab_sdk.testing.create_plugin` 创建插件，新增通知渠道还运行 `NotifierContract`；HTTP 使用 MockTransport，不启动宿主，不发送真实通知。安装包不包含测试、pyproject.toml、uv.lock、.venv 或缓存。

## 参考

- [AB 官方通知渠道接口](https://www.autobangumi.org/dev/plugins/points/notifier.html)
- [AB 消息模板扩展点](https://www.autobangumi.org/dev/plugins/points/message-template.html)
- [AB 配置表单](https://www.autobangumi.org/dev/plugins/config-forms.html)
- [Server酱³ API](https://doc.sc3.ft07.com/en/serverchan3/server/api)
- [Server酱 SDK 协议：Markdown、外部图片与响应状态码](https://doc.sc3.ft07.com/en/serverchan3/server/sdk)

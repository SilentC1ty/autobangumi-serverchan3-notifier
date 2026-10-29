"""Server酱³ 新集数 Markdown 通知渠道与系统事件模板插件。"""

from collections.abc import Mapping
from dataclasses import fields, is_dataclass

import httpx2
from ab_sdk import Plugin, hook, points, provider, secret_field
from ab_sdk.events import SystemEvent
from ab_sdk.notify import NotifierFactory, NotifierSettings, RenderedMessage
from pydantic import BaseModel, Field

from .notifier import Server3Channel
from .templates import render_template

_CHANNELS = frozenset({"server-chan", "serverchan", "server3-template"})
_MISSING = object()


class Options(BaseModel):
    """由宿主自动生成设置表单的插件配置。"""

    enabled: bool = Field(True, title="启用", description="启用 Server酱³ 通知发送和系统事件模板")
    sendkey: str = secret_field(
        title="Server酱³ SendKey",
        description="增强渠道使用的 sctp<uid>t<key>；不会自动读取内置渠道的密钥",
        repr=False,
    )
    episode_title_template: str = Field(
        "{{ title }} 第{{ season }}季 第{{ episode }}集下载完成",
        title="新集数标题模板",
        description="支持 title、official_title、season、episode、event 等变量",
    )
    episode_body_template: str = Field(
        "{{ poster }}\n\n## {{ title }}\n\n"
        "- 季度：第 {{ season }} 季\n"
        "- 集数：第 {{ episode }} 集\n"
        "- 事件：{{ event_name }}",
        title="新集数 Markdown 正文",
        description="支持 Markdown；{{ poster }} 插入海报，无海报时为空；保留换行",
    )
    title_template: str = Field(
        "{{ default_title }}",
        title="系统事件标题模板",
        description="使用 {{ variable }} 替换变量，未知变量为空字符串",
    )
    body_template: str = Field(
        "{{ default_body }}",
        title="系统事件 Markdown 正文",
        description="支持换行；多行文本可通过 config.json 中的 \\n 配置",
    )


def _build_context(message: RenderedMessage, event: SystemEvent) -> dict[str, object]:
    """收集公开事件数据，并保证四个通用变量不被事件字段覆盖。"""
    context: dict[str, object] = {}
    dataclass_event = is_dataclass(event) and not isinstance(event, type)
    if dataclass_event:
        context.update(
            (field.name, getattr(event, field.name))
            for field in fields(event)
            if not field.name.startswith("_")
        )

    # payload 是公开扩展入口；存在但读取失败时由钩子整体回退，不发送半成品。
    payload = getattr(event, "payload", _MISSING)
    if payload is not _MISSING:
        if not callable(payload):
            raise TypeError("事件 payload 必须是可调用方法")
        data = payload()
        if not isinstance(data, Mapping):
            raise TypeError("事件 payload 必须返回映射")
        context.update(
            (key, value)
            for key, value in data.items()
            if isinstance(key, str) and not key.startswith("_")
        )
    elif not dataclass_event:
        raise TypeError("事件既没有 dataclass 字段，也没有公开 payload 方法")

    kind = event.kind
    if not isinstance(kind, str) or not kind:
        raise ValueError("事件类型必须是非空字符串")
    if not isinstance(message.title, str) or not isinstance(message.body, str):
        raise TypeError("原始消息的标题与正文必须是字符串")

    # 通用变量始终对应宿主传入的消息和事件，优先于同名业务字段。
    context.update(
        default_title=message.title,
        default_body=message.body,
        event=kind,
        severity=getattr(event, "severity", ""),
    )
    return context


class Server3TemplatePlugin(Plugin[Options]):
    """通过官方通知渠道接收新集数，并保留原有系统事件模板能力。"""

    config_model = Options

    @staticmethod
    def client_factory() -> httpx2.AsyncClient:
        """为每次发送创建有超时、禁止重定向的异步 HTTP 客户端。"""
        return httpx2.AsyncClient(timeout=10, follow_redirects=False)

    @provider(points.NOTIFIER, id="server3-template")
    def channel(self) -> NotifierFactory:
        """返回独立的增强通知渠道工厂，不覆盖内置 Server Chan。"""
        def create(settings: NotifierSettings) -> Server3Channel:
            """使用插件自己的凭据和模板构造渠道，不读取宿主内部配置。"""
            return Server3Channel(self.config, settings, self.client_factory, self.ctx.log)

        return create

    @hook(points.MESSAGE_TEMPLATE)
    def render_message(
        self,
        message: RenderedMessage,
        event: SystemEvent,
        channel: str,
    ) -> RenderedMessage | None:
        """返回完整的新消息；非目标渠道、关闭或任何运行异常时保持原文案。"""
        try:
            # 先隔离渠道，其他通知渠道不会读取配置、事件或执行模板。
            if channel not in _CHANNELS:
                return None
            config = self.config
            if not config.enabled:
                return None

            context = _build_context(message, event)
            title = render_template(config.title_template, context)
            body = render_template(config.body_template, context)
            return RenderedMessage(title=title, body=body)
        except Exception:
            # 不记录消息、模板和 payload，避免把通知中的私有数据写入日志。
            try:
                self.ctx.log.warning("Server酱通知模板处理失败，已保留原始通知文案")
            except Exception:
                # 日志设施异常也不能影响宿主继续发送原始通知。
                pass
            return None

"""使用真实 SDK 测试渠道隔离、模板替换与通知回退。"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar

import pytest
from ab_sdk.events import DownloadFailureEvent, RssFailureEvent, SystemEvent
from ab_sdk.notify import RenderedMessage
from ab_sdk.testing import create_plugin

from server3_template import Options, Server3TemplatePlugin


@pytest.fixture
def message() -> RenderedMessage:
    """提供宿主传入的原始通知文案。"""
    return RenderedMessage("默认标题", "默认正文\n第二行")


@pytest.fixture
def event() -> DownloadFailureEvent:
    """提供真实 SDK 中的下载失败系统事件。"""
    return DownloadFailureEvent(official_title="示例番剧", torrent_name="示例种子.mkv")


def make_plugin(**options: object) -> Server3TemplatePlugin:
    """通过 SDK 校验配置并创建插件，不启动宿主或调用任何发送接口。"""
    plugin, _ = create_plugin(Server3TemplatePlugin, options, plugin_id="server3-template")
    return plugin


@pytest.mark.parametrize("channel", ["server-chan", "serverchan"])
def test_server_chan_channels(
    channel: str, message: RenderedMessage, event: DownloadFailureEvent
) -> None:
    """两个 Server Chan 类型均可以修改标题与正文。"""
    plugin = make_plugin(title_template="❌ {{ default_title }}", body_template="{{ event }}")
    assert plugin.render_message(message, event, channel) == RenderedMessage(
        "❌ 默认标题", "download_failure"
    )


@pytest.mark.parametrize(
    "channel",
    ["telegram", "bark", "discord", "webhook", "gotify", "pushover", "wecom",
     "server-chan-extra", "Server-Chan", "", "future-channel"],
)
def test_other_channels_do_not_read_event(channel: str, message: RenderedMessage) -> None:
    """所有非目标渠道直接跳过，即使事件完全不可读取也不受影响。"""
    assert make_plugin().render_message(message, UnreadableEvent(), channel) is None


class UnreadableEvent:
    """访问事件类型就抛错，用于证明提前返回的渠道隔离。"""

    @property
    def kind(self) -> str:
        """禁止测试中的非目标渠道读取事件。"""
        raise AssertionError("不应读取此事件")


def test_disabled_does_not_read_event(message: RenderedMessage) -> None:
    """关闭插件后不提取事件或渲染模板。"""
    assert make_plugin(enabled=False).render_message(message, UnreadableEvent(), "server-chan") is None


def test_default_templates(message: RenderedMessage, event: DownloadFailureEvent) -> None:
    """默认配置完整保留原始标题与多行正文。"""
    result = make_plugin().render_message(message, event, "server-chan")
    assert result == message
    assert result is not message


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        ("{{ default_title }}", "默认标题"),
        ("{{ default_body }}", "默认正文\n第二行"),
        ("{{ event }}", "download_failure"),
        ("{{ severity }}", "error"),
        ("{{ official_title }} / {{ torrent_name }}", "示例番剧 / 示例种子.mkv"),
        ("未知：{{ unknown }}", "未知："),
        ("{{official_title}}\n{{ official_title }}", "示例番剧\n示例番剧"),
        ("{{ official_title.upper() }} {{ default_title | upper }} {{ 1 + 1 }}",
         "{{ official_title.upper() }} {{ default_title | upper }} {{ 1 + 1 }}"),
        ("{{ official_title", "{{ official_title"),
        ("", ""),
    ],
)
def test_variable_rules(
    template: str, expected: str, message: RenderedMessage, event: DownloadFailureEvent
) -> None:
    """变量替换遵守空值、空白、重复变量与非表达式规则。"""
    result = make_plugin(body_template=template).render_message(message, event, "server-chan")
    assert result == RenderedMessage(message.title, expected)


def test_rss_payload(message: RenderedMessage) -> None:
    """另一种真实 SDK 事件自动暴露自己的公开 payload。"""
    event = RssFailureEvent(rss_name="订阅一", rss_url="https://example.com/rss", error="连接失败")
    result = make_plugin(body_template="{{ rss_name }}\n{{ rss_url }}\n{{ error }}").render_message(
        message, event, "server-chan"
    )
    assert result == RenderedMessage(message.title, "订阅一\nhttps://example.com/rss\n连接失败")


@dataclass(frozen=True, slots=True)
class FutureEvent(SystemEvent):
    """模拟未来新增、未在插件中硬编码的系统事件。"""

    kind: ClassVar[str] = "future_event"
    added_field: str = "未来字段"


def test_future_dataclass_event(message: RenderedMessage) -> None:
    """未来系统事件的新增 dataclass 字段自动成为变量。"""
    result = make_plugin(body_template="{{ added_field }} / {{ event }}").render_message(
        message, FutureEvent(), "server-chan"
    )
    assert result == RenderedMessage(message.title, "未来字段 / future_event")


@dataclass(frozen=True)
class DataclassOnlyEvent:
    """模拟仅提供 dataclass 字段、不提供 payload 或 severity 的事件。"""

    kind: ClassVar[str] = "dataclass_only"
    detail: str = "公开字段"
    _private: str = "私有字段"


def test_missing_payload_and_severity(message: RenderedMessage) -> None:
    """缺少 payload 时仍支持 dataclass，缺少 severity 与私有字段均为空。"""
    result = make_plugin(body_template="{{ detail }}|{{ severity }}|{{ _private }}").render_message(
        message, DataclassOnlyEvent(), "server-chan"
    )
    assert result == RenderedMessage(message.title, "公开字段||")


@dataclass(frozen=True)
class PayloadEvent:
    """注入公开 payload，覆盖同名字段并测试各种值与故障。"""

    kind: ClassVar[str] = "payload_event"
    severity: ClassVar[str] = "warning"
    source: Callable[[], object]
    detail: str = "dataclass 原值"

    def payload(self) -> object:
        """返回测试指定的数据，或传播由钩子负责隔离的异常。"""
        return self.source()


def test_payload_precedence_and_public_keys(message: RenderedMessage) -> None:
    """payload 优先于 dataclass，但不能覆盖通用变量或暴露私有字段。"""
    event = PayloadEvent(lambda: {
        "detail": "payload 新值", "extra": "附加字段", "_private": "私有字段",
        "default_title": "伪标题", "default_body": "伪正文", "event": "伪事件",
        "severity": "伪级别", 1: "非字符串键",
    })
    plugin = make_plugin(body_template=(
        "{{ detail }}|{{ extra }}|{{ _private }}|{{ default_title }}|"
        "{{ default_body }}|{{ event }}|{{ severity }}"
    ))
    assert plugin.render_message(message, event, "server-chan") == RenderedMessage(
        message.title, "payload 新值|附加字段||默认标题|默认正文\n第二行|payload_event|warning"
    )


class PayloadOnlyEvent:
    """模拟仅有公开 payload 的非 dataclass 数据来源。"""

    kind = "payload_only"

    def payload(self) -> dict[str, object]:
        """提供空值、数字、布尔值与含占位符的普通字符串。"""
        return {"empty": None, "number": 0, "flag": False, "literal": "{{ default_title }}"}


def test_payload_only_values_and_single_pass(message: RenderedMessage) -> None:
    """只替换一次，空值为空，零与布尔值正常转换为字符串。"""
    result = make_plugin(body_template="{{ empty }}|{{ number }}|{{ flag }}|{{ literal }}").render_message(
        message, PayloadOnlyEvent(), "server-chan"
    )
    assert result == RenderedMessage(message.title, "|0|False|{{ default_title }}")


def broken_payload() -> object:
    """模拟读取 payload 失败。"""
    raise RuntimeError("模拟事件数据读取失败")


@pytest.mark.parametrize("source", [broken_payload, lambda: None, lambda: [], lambda: "错误数据"])
def test_bad_payload_falls_back(source: Callable[[], object], message: RenderedMessage) -> None:
    """payload 异常或返回非映射时不尝试部分渲染。"""
    assert make_plugin().render_message(message, PayloadEvent(source), "server-chan") is None


@pytest.mark.parametrize("event", [object(), UnreadableEvent(), None])
def test_unusable_event_falls_back(event: object, message: RenderedMessage) -> None:
    """异常事件数据不能阻断宿主原始通知。"""
    assert make_plugin().render_message(message, event, "server-chan") is None


class BadString:
    """模拟字段转换为字符串时出错。"""

    def __str__(self) -> str:
        """抛出转换异常以验证正文失败时标题也不会部分生效。"""
        raise ValueError("模拟字段转换失败")


def test_render_failure_is_atomic(message: RenderedMessage) -> None:
    """正文渲染失败时整体回退，不输出已成功渲染的自定义标题。"""
    event = PayloadEvent(lambda: {"broken": BadString()})
    plugin = make_plugin(title_template="新标题", body_template="{{ broken }}")
    assert plugin.render_message(message, event, "server-chan") is None
    assert message == RenderedMessage("默认标题", "默认正文\n第二行")


def test_invalid_template_falls_back(message: RenderedMessage, event: DownloadFailureEvent) -> None:
    """配置模型被异常绕过时，模板类型错误也安全回退。"""
    plugin = make_plugin()
    plugin.ctx.config = Options.model_construct(enabled=True, title_template=None, body_template="正文")
    assert plugin.render_message(message, event, "server-chan") is None


def test_missing_config_falls_back(message: RenderedMessage, event: DownloadFailureEvent) -> None:
    """宿主配置读取失败时仍返回不修改。"""
    plugin = make_plugin()
    plugin.ctx.config = None
    assert plugin.render_message(message, event, "server-chan") is None


def test_input_and_other_channel_unchanged(message: RenderedMessage, event: DownloadFailureEvent) -> None:
    """改写一次后复用相同输入，不会污染原消息、事件或其他渠道。"""
    plugin = make_plugin(title_template="自定义标题", body_template="{{ torrent_name }}")
    assert plugin.render_message(message, event, "server-chan") == RenderedMessage("自定义标题", "示例种子.mkv")
    assert plugin.render_message(message, event, "telegram") is None
    assert message == RenderedMessage("默认标题", "默认正文\n第二行")
    assert event == DownloadFailureEvent(official_title="示例番剧", torrent_name="示例种子.mkv")


def test_logging_failure_still_falls_back(
    monkeypatch: pytest.MonkeyPatch, message: RenderedMessage
) -> None:
    """错误处理中的日志设施故障不能再次向宿主抛出异常。"""
    plugin = make_plugin()

    def broken_warning(*args: object, **kwargs: object) -> None:
        """模拟宿主日志后端失效。"""
        raise RuntimeError("模拟日志写入失败")

    monkeypatch.setattr(plugin.ctx.log, "warning", broken_warning)
    assert plugin.render_message(message, PayloadEvent(broken_payload), "server-chan") is None

"""用真实 SDK 与模拟 HTTP 验证新集数海报及 Server酱³ 发送行为。"""

import asyncio
import json
import logging
from collections.abc import Callable

import httpx2
import pytest
from ab_sdk.events import DownloadFailureEvent
from ab_sdk.notify import NotificationMessage, NotifierSettings, RenderedMessage
from ab_sdk.testing import NotifierContract, create_plugin

from server3_template import Options, Server3TemplatePlugin
from server3_template.notifier import Server3Channel

_KEY = "sctp123tTest_Key-456"


@pytest.fixture
def episode_message() -> NotificationMessage:
    """模拟宿主在新一集下载完成后交付的真实 SDK 消息。"""
    return NotificationMessage(
        kind="episode",
        title="示例番剧",
        body="宿主默认正文",
        official_title="示例番剧",
        season=2,
        episode=5,
        poster_url="https://ab.example.com/posters/example.jpg",
    )


def make_channel(
    handler: Callable[[httpx2.Request], httpx2.Response],
    **options: object,
) -> tuple[Server3TemplatePlugin, Server3Channel]:
    """通过 SDK 创建插件并注入模拟 HTTP，所有测试均不会访问外部服务。"""
    plugin, _ = create_plugin(
        Server3TemplatePlugin, {"sendkey": _KEY, **options}, plugin_id="server3-template"
    )

    def client_factory() -> httpx2.AsyncClient:
        """为一次测试请求提供可正确关闭的模拟客户端。"""
        return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))

    plugin.client_factory = client_factory
    channel = plugin.channel()(NotifierSettings())
    assert isinstance(channel, Server3Channel)
    return plugin, channel


def accept(request: httpx2.Request) -> httpx2.Response:
    """模拟 Server酱³ 确认接收通知。"""
    return httpx2.Response(200, json={"code": 0, "message": "成功"})


class TestServer3Contract(NotifierContract):
    """直接运行 SDK 的通知渠道契约，包括新集数、事件和拒绝响应。"""

    def create(self) -> Server3Channel:
        """创建后端接收消息的模拟通知渠道。"""
        _, channel = make_channel(accept)
        return channel

    def create_failing(self) -> Server3Channel:
        """创建 HTTP 成功但业务拒绝消息的模拟通知渠道。"""
        def reject(request: httpx2.Request) -> httpx2.Response:
            """模拟服务返回额度不足等业务错误。"""
            return httpx2.Response(200, json={"code": 1001})

        _, channel = make_channel(reject)
        return channel


def test_default_markdown_and_endpoint(episode_message: NotificationMessage) -> None:
    """默认通知包含海报、番剧、季度、集数，并只向正确的 SC3 端点发送一次。"""
    requests: list[httpx2.Request] = []

    def capture(request: httpx2.Request) -> httpx2.Response:
        """捕获唯一的推送请求，不额外请求海报。"""
        requests.append(request)
        return accept(request)

    _, channel = make_channel(capture)
    assert asyncio.run(channel.send(episode_message)) is True
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == f"https://123.push.ft07.com/send/{_KEY}.send"
    assert request.method == "POST"
    payload = json.loads(request.content)
    assert payload == {
        "title": "示例番剧 第2季 第5集下载完成",
        "desp": "![番剧海报](https://ab.example.com/posters/example.jpg)\n\n"
        "## 示例番剧\n\n- 季度：第 2 季\n- 集数：第 5 集\n- 事件：新集数下载完成",
        "short": "示例番剧 第2季 第5集下载完成",
    }


def test_custom_markdown_variables(episode_message: NotificationMessage) -> None:
    """标题与 Markdown 均支持别名、原文案、原始图片地址、事件和未知变量。"""
    captured: list[dict[str, str]] = []

    def capture(request: httpx2.Request) -> httpx2.Response:
        """记录发送正文供模板结果断言使用。"""
        captured.append(json.loads(request.content))
        return accept(request)

    _, channel = make_channel(
        capture,
        episode_title_template="[{{ event }}] {{ official_title }} S{{season}}E{{episode}}",
        episode_body_template="## {{ title }}\n\n{{ poster }}\n\n"
        "地址：{{ poster_url }}\n原文：{{ default_title }} / {{ default_body }}\n{{ unknown }}",
    )
    assert asyncio.run(channel.send(episode_message)) is True
    assert captured[0]["title"] == "[episode] 示例番剧 S2E5"
    assert "## 示例番剧\n\n![番剧海报]" in captured[0]["desp"]
    assert "地址：https://ab.example.com/posters/example.jpg" in captured[0]["desp"]
    assert captured[0]["desp"].endswith("原文：示例番剧 / 宿主默认正文\n")


@pytest.mark.parametrize("poster_url", [None, "", "file:///poster.jpg", "javascript:alert(1)"])
def test_missing_or_invalid_poster_keeps_text(poster_url: str | None) -> None:
    """无海报或非法海报地址时保留文字，不生成空的图片标记。"""
    captured: list[dict[str, str]] = []

    def capture(request: httpx2.Request) -> httpx2.Response:
        """捕获无图片时的正文。"""
        captured.append(json.loads(request.content))
        return accept(request)

    _, channel = make_channel(capture)
    message = NotificationMessage(
        kind="episode", title="番剧", body="正文", season=1, episode=1, poster_url=poster_url
    )
    assert asyncio.run(channel.send(message)) is True
    assert "番剧" in captured[0]["desp"]
    assert "第 1 集" in captured[0]["desp"]
    assert "![" not in captured[0]["desp"]


def test_poster_url_with_markdown_characters() -> None:
    """海报 URL 中的括号与空格不会破坏 Markdown 图片链接。"""
    captured: list[dict[str, str]] = []

    def capture(request: httpx2.Request) -> httpx2.Response:
        """记录有特殊字符的海报通知。"""
        captured.append(json.loads(request.content))
        return accept(request)

    _, channel = make_channel(capture, episode_body_template="{{ poster }}")
    message = NotificationMessage(
        kind="episode", title="番剧", body="正文", poster_url="https://example.com/a (1).jpg"
    )
    assert asyncio.run(channel.send(message)) is True
    assert captured[0]["desp"] == "![番剧海报](https://example.com/a%20%281%29.jpg)"


@pytest.mark.parametrize(("episode", "expected"), [(0, "0"), (5.5, "5.5"), (None, "")])
def test_fractional_and_missing_episode(episode: int | float | None, expected: str) -> None:
    """特别篇的小数集数、零和缺失值不会被错误格式化或丢失。"""
    captured: list[dict[str, str]] = []

    def capture(request: httpx2.Request) -> httpx2.Response:
        """记录边界集数的替换结果。"""
        captured.append(json.loads(request.content))
        return accept(request)

    _, channel = make_channel(capture, episode_body_template="{{ episode }}|{{ season }}")
    assert asyncio.run(channel.send(NotificationMessage(
        kind="episode", title="番剧", body="正文", episode=episode
    ))) is True
    assert captured[0]["desp"] == f"{expected}|"


def test_episode_replacements_are_not_recursive() -> None:
    """番剧标题自身含有花括号时不会再被当作模板执行。"""
    captured: list[dict[str, str]] = []

    def capture(request: httpx2.Request) -> httpx2.Response:
        """记录包含模板文本的普通番剧标题。"""
        captured.append(json.loads(request.content))
        return accept(request)

    _, channel = make_channel(capture, episode_body_template="{{ title }}")
    assert asyncio.run(channel.send(NotificationMessage(
        kind="episode", title="{{ season }}", body="正文", season=2
    ))) is True
    assert captured[0]["desp"] == "{{ season }}"


def test_template_error_falls_back_to_host_message(episode_message: NotificationMessage) -> None:
    """正文模板异常时标题与正文整体回退，仍然发送一次宿主原文案。"""
    captured: list[dict[str, str]] = []

    def capture(request: httpx2.Request) -> httpx2.Response:
        """记录回退后的实际发送内容。"""
        captured.append(json.loads(request.content))
        return accept(request)

    plugin, channel = make_channel(capture, episode_title_template="不应发送的部分标题")
    plugin.config.episode_body_template = None
    assert asyncio.run(channel.send(episode_message)) is True
    assert captured[0] == {"title": "示例番剧", "desp": "宿主默认正文", "short": "示例番剧"}


def test_empty_title_keeps_notification_sendable(episode_message: NotificationMessage) -> None:
    """用户模板渲染出空标题时使用原始标题，避免 Server酱拒绝空标题。"""
    captured: list[dict[str, str]] = []

    def capture(request: httpx2.Request) -> httpx2.Response:
        """记录空模板的标题回退。"""
        captured.append(json.loads(request.content))
        return accept(request)

    _, channel = make_channel(capture, episode_title_template="{{ unknown }}")
    assert asyncio.run(channel.send(episode_message)) is True
    assert captured[0]["title"] == "示例番剧"


def test_system_event_uses_event_hook_without_episode_template() -> None:
    """增强渠道的系统事件保留具体事件 kind 和 payload，且不会混入新集数模板。"""
    captured: list[dict[str, str]] = []

    def capture(request: httpx2.Request) -> httpx2.Response:
        """捕获按宿主两个公开阶段组合处理的系统事件。"""
        captured.append(json.loads(request.content))
        return accept(request)

    plugin, channel = make_channel(
        capture, title_template="{{ event }}", body_template="## {{ official_title }}\n{{ torrent_name }}"
    )
    event = DownloadFailureEvent(official_title="番剧一", torrent_name="种子一")
    rendered = plugin.render_message(RenderedMessage("默认标题", "默认正文"), event, "server3-template")
    assert rendered is not None
    assert asyncio.run(channel.send(NotificationMessage(
        kind="event", title=rendered.title, body=rendered.body
    ))) is True
    assert captured[0]["title"] == "download_failure"
    assert captured[0]["desp"] == "## 番剧一\n种子一"


@pytest.mark.parametrize("sendkey", ["", "SCT-Turbo-Key", "sctp123t", "sctpxtkey", "sctp1tkey/other"])
def test_invalid_sendkey_does_not_send(sendkey: str, episode_message: NotificationMessage) -> None:
    """错误、旧版或包含路径字符的密钥不会产生请求，也不会抛异常。"""
    def no_request(request: httpx2.Request) -> httpx2.Response:
        """确保无效配置没有机会访问网络。"""
        raise AssertionError("无效密钥不应触发请求")

    _, channel = make_channel(no_request, sendkey=sendkey)
    assert asyncio.run(channel.send(episode_message)) is False
    ok, detail = asyncio.run(channel.test())
    assert ok is False
    assert "SendKey" in detail


def test_disabled_channel_does_not_send(episode_message: NotificationMessage) -> None:
    """插件关闭时增强渠道不发起任何网络请求。"""
    requests: list[httpx2.Request] = []

    def capture(request: httpx2.Request) -> httpx2.Response:
        """记录任何意外发起的请求。"""
        requests.append(request)
        return accept(request)

    _, channel = make_channel(capture, enabled=False)
    assert asyncio.run(channel.send(episode_message)) is False
    assert requests == []


@pytest.mark.parametrize(
    ("status", "content"),
    [
        (200, '{"code": 1}'), (200, '{}'), (200, '{"code": "0"}'),
        (200, '{"code": false}'), (200, '[]'), (200, '不是 JSON'),
        (429, '{"code": 0}'), (503, '网关错误'), (302, '{"code": 0}'),
    ],
)
def test_rejected_or_malformed_response_returns_false(
    status: int, content: str, episode_message: NotificationMessage
) -> None:
    """服务拒绝、错误 JSON、重定向和网关错误均返回失败，不误报发送成功。"""
    def respond(request: httpx2.Request) -> httpx2.Response:
        """返回测试指定的状态码及服务响应。"""
        return httpx2.Response(status, content=content.encode("utf-8"))

    _, channel = make_channel(respond)
    assert asyncio.run(channel.send(episode_message)) is False


def test_timeout_redacts_secrets(
    episode_message: NotificationMessage, caplog: pytest.LogCaptureFixture
) -> None:
    """网络异常中即使含有密钥，返回说明和插件日志也不输出异常原文。"""
    def timeout(request: httpx2.Request) -> httpx2.Response:
        """模拟带敏感地址的网络超时异常。"""
        raise httpx2.ReadTimeout(f"敏感信息：{_KEY}", request=request)

    _, channel = make_channel(timeout)
    with caplog.at_level(logging.WARNING, logger="plugin.server3-template"):
        assert asyncio.run(channel.send(episode_message)) is False
    ok, detail = asyncio.run(channel.test())
    assert ok is False
    assert _KEY not in detail
    assert _KEY not in caplog.text
    assert "发送失败" in detail


def test_channel_test_uses_episode_template() -> None:
    """宿主渠道测试可预览新集数文字模板，不伪造无法访问的海报。"""
    captured: list[dict[str, str]] = []

    def capture(request: httpx2.Request) -> httpx2.Response:
        """捕获用户主动测试时的示例通知。"""
        captured.append(json.loads(request.content))
        return accept(request)

    _, channel = make_channel(capture, episode_title_template="{{ title }} S{{ season }}E{{ episode }}")
    assert asyncio.run(channel.test()) == (True, "Server酱³ 通知发送成功")
    assert captured[0]["title"] == "示例番剧 S1E1"
    assert "![" not in captured[0]["desp"]


def test_sendkey_is_declared_secret() -> None:
    """通过 SDK 的 secret_field 让宿主掩码凭据，配置 repr 也不暴露密钥。"""
    assert Options.model_json_schema()["properties"]["sendkey"]["secret"] is True
    assert _KEY not in repr(Options(sendkey=_KEY))

"""使用公开 SDK 数据向 Server酱³ 投递 Markdown 通知。"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import TYPE_CHECKING
from urllib.parse import quote, urlsplit

import httpx2
from ab_sdk.notify import NotificationMessage, NotifierSettings, RenderedMessage

from .templates import render_template

if TYPE_CHECKING:
    from . import Options

_SENDKEY = re.compile(r"sctp([0-9]+)t([A-Za-z0-9_-]+)\Z")


def _poster_context(poster_url: str | None) -> tuple[str, str]:
    """仅把可用的 HTTP 海报地址转换为 Markdown，无海报时返回两个空字符串。"""
    if not poster_url:
        return "", ""
    parsed = urlsplit(poster_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "", ""
    # 编码会破坏 Markdown 链接的字符；图片由 Server酱客户端读取，本插件不下载。
    image_url = quote(poster_url, safe=":/?#[]@!$&'*+,;=%~-_")
    return poster_url, f"![番剧海报]({image_url})"


class Server3Channel:
    """消费宿主的 episode/event 通知快照，发送失败通过返回值表达。"""

    def __init__(
        self,
        options: Options,
        settings: NotifierSettings,
        client_factory: Callable[[], httpx2.AsyncClient],
        logger: logging.Logger,
    ) -> None:
        """保存公开配置与客户端工厂，不进行网络访问。"""
        self.options = options
        self.settings = settings
        self.client_factory = client_factory
        self.log = logger

    def _warning(self, text: str) -> None:
        """仅记录中文固定说明，日志设施失败时不再向宿主抛出异常。"""
        try:
            self.log.warning(text)
        except Exception:
            pass

    def _render_episode(self, message: NotificationMessage) -> RenderedMessage:
        """用新集数公开字段渲染标题和 Markdown，模板异常时整体使用原文案。"""
        try:
            poster_url, poster = _poster_context(message.poster_url)
            context: dict[str, object] = {
                "title": message.official_title or message.title,
                "official_title": message.official_title or message.title,
                "season": message.season,
                "episode": message.episode,
                "poster_url": poster_url,
                "poster": poster,
                "event": message.kind,
                "event_name": "新集数下载完成",
                "default_title": message.title,
                "default_body": message.body,
            }
            # 独立的新集数模板优先；渠道原有模板渲染结果仍可用 default_body 引用。
            title = render_template(self.options.episode_title_template, context)
            body = render_template(self.options.episode_body_template, context)
            return RenderedMessage(title, body)
        except Exception:
            self._warning("新集数模板渲染失败，已使用宿主原始文案发送")
            return RenderedMessage(message.title, message.body)

    async def _post(self, message: NotificationMessage) -> tuple[bool, str]:
        """校验 Server酱³ 密钥并投递一次，不重试以免产生重复通知。"""
        try:
            if not self.options.enabled:
                return False, "插件已关闭"
            sendkey = self.options.sendkey.strip()
            key = _SENDKEY.fullmatch(sendkey)
            if key is None:
                return False, "请在插件设置中填写有效的 Server酱³ SendKey（sctp<uid>t<key>）"
            url = f"https://{key.group(1)}.push.ft07.com/send/{sendkey}.send"

            # 系统事件已在宿主 message_template 阶段处理，不把它当作新集数再渲染。
            rendered = (
                self._render_episode(message)
                if message.kind == "episode"
                else RenderedMessage(message.title, message.body)
            )
            title = rendered.title.strip() or message.title.strip() or "AutoBangumi 通知"
            data = {"title": title, "desp": rendered.body, "short": title}
            async with self.client_factory() as client:
                response = await client.post(url, json=data)

            if not response.is_success:
                return False, f"Server酱³ 请求失败，HTTP 状态码：{response.status_code}"
            result = response.json()
            # 官方接口以 code == 0 表示成功，HTTP 200 不代表业务成功。
            code = result.get("code") if isinstance(result, dict) else None
            if type(code) is not int or code != 0:
                return False, "Server酱³ 未确认接收成功，请检查密钥、额度和服务状态"
            return True, "Server酱³ 通知发送成功"
        except Exception:
            # 不输出异常原文、请求地址或服务响应，避免 SendKey 和通知内容进入日志。
            return False, "Server酱³ 发送失败，请检查网络、配置和服务响应"

    async def send(self, message: NotificationMessage) -> bool:
        """发送宿主交付的一条通知，任何普通运行异常都返回 False。"""
        ok, detail = await self._post(message)
        if not ok:
            self._warning(detail)
        return ok

    async def test(self) -> tuple[bool, str]:
        """由用户点击渠道测试时发送示例新集数，不伪造可用海报地址。"""
        return await self._post(
            NotificationMessage(
                kind="episode",
                title="AutoBangumi 通知测试",
                body="这是新集数模板测试；真实通知的海报由 AutoBangumi 提供。",
                official_title="示例番剧",
                season=1,
                episode=1,
            )
        )

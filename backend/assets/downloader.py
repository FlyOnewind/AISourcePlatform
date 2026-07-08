"""HTTP 下载工具模块。

提供统一的 URL 下载函数，支持普通 HTTP/HTTPS URL、微信微盘分享链接等，
供 image_link、video_link、document_link 等链接类型资源处理使用。
"""

import json
import logging
import re
import time
from pathlib import Path
from threading import Lock
from urllib.request import Request, urlopen
from urllib.error import URLError

import httpx

logger = logging.getLogger(__name__)

# 默认 HTTP 请求超时时间（秒）
DEFAULT_TIMEOUT = 30

# 微信微盘分享链接正则（匹配 drive.weixin.qq.com/s?k=xxx）
_WECHAT_DRIVE_SHARE_RE = re.compile(
    r"^https?://drive\.weixin\.qq\.com/s\?k=([a-zA-Z0-9_-]+)",
    re.IGNORECASE,
)

# 通用浏览器 UA
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# ── 路径一：企业微信开放 API（管理员，长期有效）────────────────────

_access_token_cache: dict = {"token": "", "expires_at": 0.0}
_access_token_lock = Lock()


def _get_corp_token() -> str:
    """获取企业微信 access_token（自动缓存，过期前 5 分钟刷新）。

    需在 .env 中配置 WECHAT_CORPID 和 WECHAT_CORPSECRET。
    """
    global _access_token_cache

    if _access_token_cache["token"] and time.time() < _access_token_cache["expires_at"]:
        return _access_token_cache["token"]

    with _access_token_lock:
        if _access_token_cache["token"] and time.time() < _access_token_cache["expires_at"]:
            return _access_token_cache["token"]

        try:
            from app.core.config import get_settings
            cfg = get_settings()
            corpid = cfg.wechat_corpid
            corpsecret = cfg.wechat_corpsecret
        except Exception:
            return ""

        if not corpid or not corpsecret:
            return ""

        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(
                    "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
                    params={"corpid": corpid, "corpsecret": corpsecret},
                    headers={"User-Agent": _BROWSER_UA},
                )
                resp.raise_for_status()
                result = resp.json()
            if result.get("errcode") == 0:
                token = result["access_token"]
                expires_in = result.get("expires_in", 7200)
                _access_token_cache = {
                    "token": token,
                    "expires_at": time.time() + expires_in - 300,
                }
                logger.debug("已获取企业微信 access_token（有效期 %ds）", expires_in)
                return token
            else:
                logger.warning("获取 access_token 失败: %s", result.get("errmsg"))
        except Exception:
            logger.warning("请求 access_token 网络异常", exc_info=True)
    return ""


def _enterprise_download(file_id: str, file_name: str, timeout: int) -> bytes:
    """通过企业微信开放 API 下载微盘文件。

    调用 file_download API 获取下载链接，然后下载文件内容。
    企业 API 返回的 download_url 通常不需要额外 Cookie。
    """
    token = _get_corp_token()
    if not token:
        raise ValueError("未配置 WECHAT_CORPID / WECHAT_CORPSECRET")

    # 1) 获取下载链接
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(
            "https://qyapi.weixin.qq.com/cgi-bin/wedrive/file_download",
            params={"access_token": token},
            json={"fileid": file_id},
            headers={"User-Agent": _BROWSER_UA},
        )
        if resp.status_code != 200:
            raise ValueError(f"企业微信 API 返回 HTTP {resp.status_code}")
        result = resp.json()
        if result.get("errcode") != 0:
            raise ValueError(
                f"获取下载链接失败: {result.get('errmsg', '未知错误')} "
                f"(errcode={result.get('errcode')})"
            )
        download_url = result.get("download_url", "")
        if not download_url:
            raise ValueError("企业微信 API 返回空的下载链接")

    # 2) 下载文件（企业 API 返回的 URL 直接可用）
    logger.debug("企业 API 下载: %s → %s", file_name, download_url[:80])
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        dl_resp = client.get(download_url, headers={"User-Agent": _BROWSER_UA})
        dl_resp.raise_for_status()
        return dl_resp.content


# ── 路径二：Playwright 浏览器（非管理员，一次扫码长期复用）──────────

def _browser_download(url: str, file_name: str, timeout: int) -> bytes:
    """通过 Playwright 持久化浏览器下载微盘文件。

    使用 ~/.kb_wechat_profile/ 保存登录态，首次需扫码，后续自动复用。
    下载完成后不关闭浏览器 profile，供下次复用。
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(
            "需要安装 Playwright: pip install playwright && playwright install chromium"
        )

    profile_dir = Path.home() / ".kb_wechat_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)

    logger.info("正在打开浏览器（首次需扫码登录企业微信）...")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False,
            locale="zh-CN",
        )
        page = context.new_page()

        # 导航到分享页
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)

        # 如果需要登录，等待用户扫码完成 OAuth 流程
        login_locator = page.locator('button:has-text("登录查看")')
        if login_locator.is_visible():
            logger.info(
                "══════════════════════════════════════════\n"
                "  请在浏览器窗口中扫码登录企业微信\n"
                "  文件: %s\n"
                "  登录完成后系统自动继续\n"
                "  等待时间: 最多 3 分钟\n"
                "══════════════════════════════════════════",
                file_name,
            )
            try:
                # 等待登录按钮消失（页面跳转到 OAuth）
                login_locator.wait_for(state="hidden", timeout=30_000)
                # 等待 OAuth 完成后跳回分享页
                page.wait_for_url(
                    f"**/s?k=*#/",
                    timeout=150_000,
                )
                page.wait_for_timeout(3000)
            except Exception:
                context.close()
                raise RuntimeError("等待登录超时（3 分钟），请重试")

        # 等待页面渲染完毕
        page.wait_for_timeout(2000)

        # 尝试多种选择器找到下载按钮
        selectors = [
            '.share_file_download',
            'button:has-text("下载")',
            '[class*="download"]',
            'button:has-text("Download")',
            'a:has-text("下载")',
        ]
        download_btn = None
        for sel in selectors:
            download_btn = page.query_selector(sel)
            if download_btn:
                logger.debug("找到下载按钮: %s", sel)
                break

        if not download_btn:
            # 最后尝试：截图保存用于调试
            try:
                page.screenshot(path=str(profile_dir.parent / ".kb_debug.png"))
                logger.debug("已保存调试截图: ~/.kb_debug.png")
            except Exception:
                pass
            # 打印页面文本帮助定位
            body_text = page.text_content("body") or ""
            logger.warning("页面文本前 500 字: %s", body_text[:500])
            context.close()
            raise RuntimeError(
                "未找到下载按钮，页面结构可能已变更。"
                "调试截图已保存至 ~/.kb_debug.png"
            )

        # 用 Playwright 的 download 事件捕获下载
        with page.expect_download(timeout=timeout * 1000) as download_info:
            download_btn.click()

        download = download_info.value
        data = download.path().read_bytes()
        logger.info("浏览器下载完成: %s (%d bytes)", file_name, len(data))
        context.close()
        return data


# ── 页面解析（两条路径共用）─────────────────────────────────────────

def _parse_share_page(url: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """获取微信微盘分享页，从中提取文件元数据。"""
    logger.debug("获取微盘分享页: %s", url)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.get(
            url,
            headers={
                "User-Agent": _BROWSER_UA,
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        resp.raise_for_status()
        html = resp.text

    # 提取 xd_global_shareInitDate = {...}
    match = re.search(
        r'xd_global_shareInitDate\s*=\s*(\{.*?\})\s*</script>',
        html,
        re.DOTALL,
    )
    if not match:
        raise ValueError("无法从页面中解析微盘文件信息，链接可能已失效")

    # JS 对象字面量 → JSON
    js_text = match.group(1)
    js_text = re.sub(r"\bBoolean\(true\)", "true", js_text)
    js_text = re.sub(r"\bBoolean\(false\)", "false", js_text)
    js_text = re.sub(r"\bBoolean\(\s*\)", "false", js_text)
    js_text = re.sub(r"\bNumber\((-?\d+)\)", r"\1", js_text)
    js_text = re.sub(r"\bNumber\(\s*\)", "0", js_text)
    js_text = re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), js_text)
    js_text = re.sub(r",\s*([}\]])", r"\1", js_text)

    try:
        return json.loads(js_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"解析微盘页面数据失败: {exc}") from exc


# ── 统一下载入口 ──────────────────────────────────────────────────────

def download_to_bytes(url: str, timeout: int = DEFAULT_TIMEOUT) -> bytes:
    """从 HTTP/HTTPS URL 下载资源，返回原始字节。

    支持普通 URL 和微信微盘分享链接（drive.weixin.qq.com/s?k=xxx）。
    微盘下载自动选择：企业 API（管理员）或浏览器扫码（非管理员）。

    Args:
        url: 资源 URL。
        timeout: 请求超时时间（秒）。

    Returns:
        下载的原始字节数据。

    Raises:
        ValueError: URL 不合法或下载失败。
        URLError: 普通 URL 网络不可达。
        RuntimeError: 微盘浏览器登录超时。
    """
    if not url:
        raise ValueError("下载 URL 不能为空")

    # ── 微信微盘分享链接 ──
    if _WECHAT_DRIVE_SHARE_RE.match(url):
        share_data = _parse_share_page(url, timeout)
        file_id = share_data.get("file_id", "")
        file_name = share_data.get("object_name", "未知文件")
        auth_type = share_data.get("auth_type", 0)

        # 路径一：企业 API（管理员，长期有效）
        if _get_corp_token():
            logger.info("微盘下载 [企业API]: %s", file_name)
            try:
                return _enterprise_download(file_id, file_name, timeout)
            except Exception:
                logger.warning("企业 API 下载失败，尝试浏览器方式", exc_info=True)

        # 路径二：浏览器扫码（非管理员）
        if auth_type == 0:
            # 公开分享：直接尝试 HTTP 下载（页面中的 download_url）
            download_url = share_data.get("download_url", "")
            if download_url:
                with httpx.Client(timeout=timeout, follow_redirects=True) as c:
                    return c.get(download_url, headers={"User-Agent": _BROWSER_UA}).content
            raise ValueError(f"微盘文件「{file_name}」下载链接为空，请确认分享有效")

        logger.info("微盘下载 [浏览器]: %s", file_name)
        return _browser_download(url, file_name, timeout)

    # ── 普通 HTTP/HTTPS URL ──
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"不支持的协议: {url}")

    logger.debug("开始下载: %s", url)
    req = Request(url, headers={"User-Agent": "KnowledgeBase/1.0"})
    try:
        with urlopen(req, timeout=timeout) as response:
            data = response.read()
            logger.debug("下载完成: %s (%d bytes)", url, len(data))
            return data
    except URLError as exc:
        logger.warning("下载失败: %s (%s)", url, exc)
        raise

"""
飞书消息推送封装。
职责：同时兼容「飞书开放平台自建应用机器人」与「群自定义机器人 Webhook（含签名校验）」，供所有 Agent 复用。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import requests

from core.config import Settings, get_logger

logger = get_logger("core.notify.feishu")


class FeishuNotifier:
    """
    飞书通知器：支持纯文本消息与交互式 Markdown 卡片推送。
    """

    def __init__(self, settings: Settings) -> None:
        self.app_id = settings.feishu_app_id
        self.app_secret = settings.feishu_app_secret
        self.default_receive_id = settings.feishu_receive_id
        self.default_receive_id_type = settings.feishu_receive_id_type
        self.webhook_url = settings.feishu_webhook_url
        self.webhook_secret = settings.feishu_webhook_secret

    def _get_tenant_access_token(self) -> str:
        """
        调用飞书开放平台接口换取自建应用的 tenant_access_token。
        """
        resp = requests.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": self.app_id, "app_secret": self.app_secret},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"获取飞书 tenant_access_token 失败: {data}")
        return data["tenant_access_token"]

    @staticmethod
    def _build_webhook_sign(timestamp: str, secret: str) -> str:
        """
        按飞书自定义机器人安全设置生成 HmacSHA256 签名。
        飞书规范：以 "timestamp\\nsecret" 作为 key，对空字节串计算 HMAC-SHA256 后进行 Base64 编码。
        """
        string_to_sign = f"{timestamp}\n{secret}"
        hmac_code = hmac.new(
            string_to_sign.encode("utf-8"), digestmod=hashlib.sha256
        ).digest()
        return base64.b64encode(hmac_code).decode("utf-8")

    def send_text(
        self,
        text: str,
        *,
        receive_id: str | None = None,
        receive_id_type: str | None = None,
    ) -> None:
        """
        发送纯文本消息到飞书（还原 Dify 工作流中的 send_bot_message 行为）。
        若同时配置了自建应用与 Webhook，会按配置依次投递；若均未配置则抛出配置异常。
        """
        delivered = False

        # 通道 1：飞书开放平台自建应用（支持发往任意已拉入机器人的群 chat_id 或个人 open_id）
        if self.app_id and self.app_secret and not self.app_id.startswith("cli_在这里"):
            token = self._get_tenant_access_token()
            target_id = receive_id or self.default_receive_id
            target_type = receive_id_type or self.default_receive_id_type

            resp = requests.post(
                "https://open.feishu.cn/open-apis/im/v1/messages",
                params={"receive_id_type": target_type},
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "receive_id": target_id,
                    "msg_type": "text",
                    "content": json.dumps({"text": text}, ensure_ascii=False),
                },
                timeout=15,
            )
            resp.raise_for_status()
            res_json = resp.json()
            if res_json.get("code") != 0:
                raise RuntimeError(f"飞书应用消息发送失败: {res_json}")
            logger.info("飞书自建应用消息发送成功 | receive_id=%s", target_id)
            delivered = True

        # 通道 2：飞书群自定义机器人 Webhook
        if self.webhook_url:
            body: dict = {
                "msg_type": "text",
                "content": {"text": text},
            }
            if self.webhook_secret:
                ts = str(int(time.time()))
                body["timestamp"] = ts
                body["sign"] = self._build_webhook_sign(ts, self.webhook_secret)

            wh_resp = requests.post(self.webhook_url, json=body, timeout=15)
            wh_resp.raise_for_status()
            wh_json = wh_resp.json()
            if wh_json.get("code", 0) != 0:
                raise RuntimeError(f"飞书 Webhook 消息发送失败: {wh_json}")
            logger.info("飞书 Webhook 消息发送成功")
            delivered = True

        if not delivered:
            raise ValueError(
                "未配置有效的飞书推送凭证（FEISHU_APP_ID/FEISHU_APP_SECRET 或 FEISHU_WEBHOOK_URL），"
                "本地调试可使用 --dry-run 跳过推送。"
            )

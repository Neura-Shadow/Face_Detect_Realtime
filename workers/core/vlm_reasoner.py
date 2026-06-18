from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from typing import Any, Protocol, runtime_checkable

import numpy as np

try:
    import httpx
    _HAS_HTTPX = True
except ImportError:
    _HAS_HTTPX = False

from .config import AgentConfig, VLMConfig, VLMOutput, Hazard, NavigableRegion, WaypointHint

logger = logging.getLogger(__name__)

# ============================================================
# VLMReasoner Protocol
# ============================================================

@runtime_checkable
class VLMReasoner(Protocol):
    """
    VLM 推理器介面定義（Protocol）
    所有具體 VLM 轉接器均需遵循此介面。
    """
    async def reason(
        self,
        frame: np.ndarray,
        context: dict[str, Any],
    ) -> VLMOutput:
        """
        對單張影像進行語義推理與危害檢測。
        Args:
            frame: BGR 格式的 numpy 影像
            context: 包含感知結果與車輛狀態的上下文資訊字典
        Returns:
            VLMOutput 結構化推理結果
        """
        ...


# ============================================================
# Local Stub VLM 推理器（用於本地無網路/Mock 模式開發）
# ============================================================

class LocalStubReasoner(VLMReasoner):
    """
    本地 VLM stub 推理器。
    不進行任何網路呼叫，直接返回模擬的 VLMOutput，保證符合 JSON Schema。
    """
    async def reason(
        self,
        frame: np.ndarray,
        context: dict[str, Any],
    ) -> VLMOutput:
        logger.info("LocalStubReasoner: 產生模擬 VLM 推理結果")
        # 模擬一個簡單的前方障礙物場景
        return VLMOutput(
            scene_summary="[MOCK/STUB] 前方路徑通暢，右側偵測到一名行人，前方 5 米處有障礙物標誌。",
            reasoning_summary="行人位於右前方且距離尚有安全裕度，應向左微調並減速以確保安全。無其他高危險特徵。",
            hazards=[
                Hazard(
                    label="pedestrian",
                    severity="medium",
                    bbox=None,
                    description="右側路旁行人，可能橫穿馬路"
                )
            ],
            navigable_regions=[
                NavigableRegion(
                    region_id="left_lane",
                    description="左側車道可行駛",
                    confidence=0.9
                ),
                NavigableRegion(
                    region_id="center_lane",
                    description="中央行駛路徑",
                    confidence=0.85
                )
            ],
            waypoint_hints=[
                WaypointHint(
                    hint="向左微調避讓行人並減速",
                    direction="forward",
                    distance_hint="5m",
                    priority=1
                )
            ],
            speed_hint="slow",
            must_not_do=["accelerate", "turn_right"],
            confidence=0.8
        )


# ============================================================
# OpenAI-Compatible VLM 推理器
# ============================================================

class OpenAICompatibleReasoner(VLMReasoner):
    """
    使用 OpenAI 規格的 Chat Completions + Vision API 進行 VLM 推理。
    支援超時、自動重試，並在徹底失敗時降級回 LocalStubReasoner。
    """
    _SYSTEM_PROMPT: str = (
        "你是一個自動駕駛車輛的視覺語言模型代理（VLM Agent）。\n"
        "請分析提供的相機影像與上下文資訊，並嚴格按照以下 JSON Schema 輸出結構化分析結果：\n"
        "{\n"
        '  "scene_summary": "影像自然語言場景描述",\n'
        '  "reasoning_summary": "A concise explanation of the decision basis. Do not include hidden chain-of-thought.",\n'
        '  "hazards": [\n'
        '    {\n'
        '      "label": "障礙物/危害標籤",\n'
        '      "severity": "low|medium|high|critical",\n'
        '      "description": "危害描述"\n'
        '    }\n'
        '  ],\n'
        '  "navigable_regions": [\n'
        '    {\n'
        '      "region_id": "區域識別碼",\n'
        '      "description": "可行駛區域描述",\n'
        '      "confidence": 0.0~1.0\n'
        '    }\n'
        '  ],\n'
        '  "waypoint_hints": [\n'
        '    {\n'
        '      "hint": "導航點提示描述",\n'
        '      "direction": "forward|left|right|back|stop",\n'
        '      "distance_hint": "預估距離 (例如: 3m)",\n'
        '      "priority": 1\n'
        '    }\n'
        '  ],\n'
        '  "speed_hint": "stop|slow|normal",\n'
        '  "must_not_do": ["絕對禁止採取的行動 (例如: turn_left, accelerate)"],\n'
        '  "confidence": 0.0~1.0\n'
        "}\n"
        "注意：請只輸出純 JSON 字串，不要包含任何 markdown 標記（如 ```json）或額外解釋文字。"
    )

    def __init__(self, config: VLMConfig | None = None) -> None:
        cfg = config or AgentConfig.load().vlm
        self._api_base = cfg.api_base.rstrip("/") if cfg.api_base else ""
        self._model = cfg.model
        self._api_key = cfg.api_key
        self._timeout = cfg.timeout_sec
        self._max_retries = cfg.max_retries
        self._temperature = cfg.temperature
        self._max_tokens = cfg.max_tokens
        self._confidence_threshold = cfg.confidence_threshold

        self._stub = LocalStubReasoner()

        if not _HAS_HTTPX:
            logger.warning("未安裝 httpx 庫，OpenAICompatibleReasoner 將會降級至 LocalStubReasoner")

        logger.info(
            "OpenAICompatibleReasoner 初始化完成。Endpoint: %s, Model: %s",
            self._api_base,
            self._model
        )

    async def reason(
        self,
        frame: np.ndarray,
        context: dict[str, Any],
    ) -> VLMOutput:
        if not _HAS_HTTPX or not self._api_base or not self._model:
            logger.info("VLM API 未配置，直接使用 LocalStubReasoner")
            return await self._stub.reason(frame, context)

        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 2):
            try:
                return await self._call_api(frame, context, attempt)
            except asyncio.TimeoutError:
                logger.warning("VLM 呼叫超時 (嘗試 %d/%d)", attempt, self._max_retries + 1)
                last_error = asyncio.TimeoutError(f"VLM timeout after {self._timeout}s")
            except Exception as exc:
                logger.warning("VLM 呼叫失敗 (嘗試 %d/%d): %s", attempt, self._max_retries + 1, exc)
                last_error = exc
            
            # 指數退避延遲
            if attempt <= self._max_retries:
                await asyncio.sleep(0.5 * attempt)

        logger.error("VLM API 呼叫多次重試均失敗，降級使用 LocalStubReasoner。原因: %s", last_error)
        return await self._stub.reason(frame, context)

    async def _call_api(
        self,
        frame: np.ndarray,
        context: dict[str, Any],
        attempt: int,
    ) -> VLMOutput:
        image_b64 = self._encode_frame(frame)

        user_content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": f"當前車輛狀態與環境上下文：{json.dumps(context, ensure_ascii=False)}"
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{image_b64}"
                }
            }
        ]

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": self._SYSTEM_PROMPT},
                {"role": "user", "content": user_content}
            ],
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
            "response_format": {"type": "json_object"}
        }

        headers = {"Content-Type": "application/json"}
        if self._api_key and self._api_key != "optional":
            headers["Authorization"] = f"Bearer {self._api_key}"

        start_time = time.monotonic()
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._api_base}/chat/completions",
                json=payload,
                headers=headers
            )
            response.raise_for_status()

        latency_ms = int((time.monotonic() - start_time) * 1000)
        result_json = response.json()
        content = result_json["choices"][0]["message"]["content"]
        
        parsed_output = self._parse_response(content)
        logger.info(
            "VLM 推理成功 (嘗試 %d): confidence=%.2f, 耗時=%dms",
            attempt,
            parsed_output.confidence,
            latency_ms
        )
        return parsed_output

    def _encode_frame(self, frame: np.ndarray) -> str:
        try:
            import cv2
            success, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if success:
                return base64.b64encode(encoded.tobytes()).decode("utf-8")
        except ImportError:
            pass

        try:
            import io
            from PIL import Image as PILImage
            rgb = frame[:, :, ::-1] if frame.ndim == 3 else frame
            pil_img = PILImage.fromarray(rgb)
            buf = io.BytesIO()
            pil_img.save(buf, format="JPEG", quality=80)
            return base64.b64encode(buf.getvalue()).decode("utf-8")
        except Exception:
            logger.warning("影像 Base64 編碼失敗，使用空影像字串")
            return base64.b64encode(b"").decode("utf-8")

    def _parse_response(self, content: str) -> VLMOutput:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            json_lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(json_lines)

        try:
            parsed = json.loads(cleaned)
            return VLMOutput.model_validate(parsed)
        except Exception as exc:
            logger.warning("VLM 輸出 JSON 解析錯誤: %s，使用降級安全設定。原始輸出: %s", exc, content)
            return VLMOutput(
                scene_summary=f"[解析錯誤] 原始 VLM 輸出: {content[:100]}",
                reasoning_summary="因輸出格式錯誤，已退回安全預設狀態。",
                hazards=[],
                navigable_regions=[],
                waypoint_hints=[],
                speed_hint="stop",
                must_not_do=["forward"],
                confidence=0.1
            )


# ============================================================
# Gemma 推理器（適配器繼承自 OpenAICompatibleReasoner）
# ============================================================

class GemmaReasoner(OpenAICompatibleReasoner):
    """
    Gemma 4 VLM 轉接適配器。
    繼承自 OpenAICompatibleReasoner，保留 Gemma 的專屬設定。
    """
    def __init__(self, config: VLMConfig | None = None) -> None:
        super().__init__(config)
        # Gemma 模型對於純 JSON 輸出的遵從度較不穩定，因此我們加強其 System Prompt
        self._SYSTEM_PROMPT = self._SYSTEM_PROMPT.replace(
            "注意：請只輸出純 JSON 字串，不要包含任何 markdown 標記（如 ```json）或額外解釋文字。",
            "CRITICAL INSTRUCTION: You MUST output ONLY valid JSON. Absolutely NO markdown formatting, NO backticks, NO code blocks, and NO conversational text before or after the JSON object. Just the raw JSON object."
        )
        logger.info("GemmaReasoner (VLMReasoner) 已裝載並加強 JSON 遵從性提示。")


# ============================================================
# 相容性命名別名
# ============================================================

OpenAICompatibleVLMReasoner = OpenAICompatibleReasoner
LocalStubVLMReasoner = LocalStubReasoner

# ============================================================
# CLI Self-Test
# ============================================================

async def _run_test(provider_name: str) -> None:
    logging.basicConfig(level=logging.INFO)
    logger.info(f"執行 VLM Reasoner Self-Test: {provider_name}")
    
    config = AgentConfig.load()
    import dataclasses
    config = dataclasses.replace(config, vlm=dataclasses.replace(config.vlm, provider=provider_name))

    if provider_name == "local_stub":
        reasoner = LocalStubReasoner()
    elif provider_name == "gemma":
        reasoner = GemmaReasoner(config.vlm)
    elif provider_name == "openai_compatible":
        reasoner = OpenAICompatibleReasoner(config.vlm)
    else:
        logger.error(f"未知的 provider: {provider_name}")
        return

    # 建立一個全黑測試影像
    dummy_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    dummy_context = {
        "speed": 0.0,
        "lane": "center",
        "planner_state": "idle",
        "detections": []
    }

    logger.info("開始呼叫 reason()...")
    start_t = time.monotonic()
    try:
        result = await reasoner.reason(dummy_frame, dummy_context)
        latency = time.monotonic() - start_t
        logger.info(f"推理完成！耗時 {latency:.2f}s")
        logger.info(f"Scene Summary: {result.scene_summary}")
        logger.info(f"Reasoning Summary: {result.reasoning_summary}")
        logger.info(f"Confidence: {result.confidence}")
    except Exception as e:
        logger.error(f"推理過程中發生例外: {e}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="VLM Reasoner CLI Self-Test")
    parser.add_argument("--test", type=str, required=True, choices=["local_stub", "openai_compatible", "gemma"], help="Provider to test")
    args = parser.parse_args()

    asyncio.run(_run_test(args.test))

"""图片版简历的文字识别（OCR）。

图片没有 PDF 那样天然的文本层，靠多模态模型"看图识字"。默认走硅基流动账号下的
DeepSeek-OCR（实测最快），失败/超时再依次换 Qwen3-VL-8B、PaddleOCR-VL-1.5。
复用跟 EMBEDDING_* 一样的 OpenAI 兼容 /chat/completions 接口，不需要新增系统级
依赖（不用装 tesseract 之类的本地 OCR 引擎）。
"""

import base64
import logging

from openai import OpenAI

import config

logger = logging.getLogger(__name__)

# DeepSeek-OCR 官方推荐的"无版面纯文本"提示词（见 DeepSeek-OCR README：
# without layouts: "<image>\nFree OCR."）。用自然语言长提示反而会触发它吐
# 出一段"当前模式为…"之类的元说明，污染识别结果。
_DEEPSEEK_OCR_PROMPT = "Free OCR."

# Qwen / Paddle 等通用视觉模型用自然语言约束更稳。
_GENERIC_OCR_PROMPT = (
    "你是专业的简历 OCR 识别助手。请识别图片中的所有文字内容，按图片中的原始排版顺序"
    "（从上到下、从左到右）输出为纯文本，保留换行，不要翻译、不要总结、不要分类、"
    "不要添加任何解释/标签/代码块标记/与识别无关的前后缀说明，只输出识别到的原文文字，"
    "不要输出图片里没有出现过的内容。"
)

_EXT_TO_MIME = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
}


def _prompt_for_model(model: str) -> str:
    if "deepseek-ocr" in model.lower():
        return _DEEPSEEK_OCR_PROMPT
    return _GENERIC_OCR_PROMPT


def extract_text_from_image(image_bytes: bytes, image_ext: str) -> str:
    """调用 OCR 模型识别图片简历中的文字，返回识别出的纯文本。

    先试首选模型（OCR_MODEL），单个模型超过 OCR_TIMEOUT_SECONDS 或报错就换下一个
    候选模型（OCR_FALLBACK_MODELS）重试，跟聊天 LLM 的主备切换是同一个思路——
    只是这里换的是候选模型列表而不是单个 fallback，因为都在同一个硅基流动账号/
    同一套 OpenAI 兼容接口下，不需要换 Key/base_url。
    全部模型都失败时才抛出异常，由调用方（server.py）决定如何降级。
    """
    if not config.OCR_ENABLED:
        raise RuntimeError("OCR 功能未启用（OCR_ENABLED=false）")
    if not image_bytes:
        raise ValueError("图片内容为空")

    mime = _EXT_TO_MIME.get(image_ext.lower().lstrip("."), "image/png")
    encoded = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:{mime};base64,{encoded}"

    # max_retries=0：换模型重试的逻辑已经在下面的循环里做了，openai SDK 自带的
    # 自动重试（默认最多重试 2 次）会让"单个模型的超时预算"被成倍放大——一次
    # create() 调用最坏情况下等于 OCR_TIMEOUT_SECONDS × (1 + 默认重试次数)，
    # 跟外层按"1 个模型 = 1 份超时预算"算出来的总超时对不上，会导致明明该换
    # 下一个模型了，却还在同一个慢模型上反复原地重试。
    client = OpenAI(
        api_key=config.OCR_API_KEY,
        base_url=config.OCR_BASE_URL,
        timeout=config.OCR_TIMEOUT_SECONDS,
        max_retries=0,
    )
    models = [config.OCR_MODEL, *config.OCR_FALLBACK_MODELS]

    last_error: Exception | None = None
    for model in models:
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": data_url}},
                            {"type": "text", "text": _prompt_for_model(model)},
                        ],
                    }
                ],
            )
            text = (response.choices[0].message.content or "").strip()
            if text:
                return text
            last_error = RuntimeError(f"模型 {model} 未识别到任何文字")
        except Exception as exc:
            logger.warning("OCR 模型 %s 调用失败，尝试下一个候选模型：%s", model, exc)
            last_error = exc

    raise RuntimeError(f"所有 OCR 候选模型均识别失败（已尝试 {len(models)} 个）：{last_error}")

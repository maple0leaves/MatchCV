"""Tests for ocr.resume_ocr.extract_text_from_image 及 /api/internal/ocr-resume。"""

import base64
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import config
from ocr.resume_ocr import _prompt_for_model, extract_text_from_image


def test_prompt_for_model_uses_free_ocr_for_deepseek():
    """DeepSeek-OCR 必须用官方 Free OCR. 提示词，否则会吐出模式说明污染结果。"""
    assert _prompt_for_model("deepseek-ai/DeepSeek-OCR") == "Free OCR."
    assert _prompt_for_model("Qwen/Qwen3-VL-8B-Instruct") != "Free OCR."


def _fake_openai_response(text: str):
    message = MagicMock()
    message.content = text
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def test_extract_text_from_image_returns_recognized_text():
    with patch("ocr.resume_ocr.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _fake_openai_response("张三\n具备 Python 基础的硕士生\n5年经验")
        mock_openai_cls.return_value = mock_client

        text = extract_text_from_image(b"fake-png-bytes", "png")

        assert text == "张三\n具备 Python 基础的硕士生\n5年经验"

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == config.OCR_MODEL
        image_url = call_kwargs["messages"][0]["content"][0]["image_url"]["url"]
        assert image_url.startswith("data:image/png;base64,")


def test_extract_text_from_image_raises_when_all_models_recognize_no_text():
    """首选和所有候选模型都识别不出文字时，才最终报错（不是首选一失手就直接报错）。"""
    with patch("ocr.resume_ocr.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _fake_openai_response("   ")
        mock_openai_cls.return_value = mock_client

        with pytest.raises(RuntimeError, match="所有 OCR 候选模型均识别失败"):
            extract_text_from_image(b"fake-png-bytes", "png")

        expected_attempts = 1 + len(config.OCR_FALLBACK_MODELS)
        assert mock_client.chat.completions.create.call_count == expected_attempts


def test_extract_text_from_image_falls_back_to_next_model_when_primary_errors():
    """首选模型调用报错（如超时）时自动换下一个候选模型，而不是直接失败。"""
    with patch("ocr.resume_ocr.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [
            TimeoutError("首选模型超时"),
            _fake_openai_response("Zhang San\nPython Engineer"),
        ]
        mock_openai_cls.return_value = mock_client

        text = extract_text_from_image(b"fake-png-bytes", "png")

        assert text == "Zhang San\nPython Engineer"
        assert mock_client.chat.completions.create.call_count == 2
        first_model = mock_client.chat.completions.create.call_args_list[0].kwargs["model"]
        second_model = mock_client.chat.completions.create.call_args_list[1].kwargs["model"]
        assert first_model == config.OCR_MODEL
        assert second_model == config.OCR_FALLBACK_MODELS[0]


def test_extract_text_from_image_raises_when_every_student_model_errors():
    """首选和所有候选模型全部报错时，最终异常信息里带上尝试过的模型数量。"""
    with patch("ocr.resume_ocr.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = RuntimeError("模型不可用")
        mock_openai_cls.return_value = mock_client

        expected_attempts = 1 + len(config.OCR_FALLBACK_MODELS)
        with pytest.raises(RuntimeError, match=f"已尝试 {expected_attempts} 个"):
            extract_text_from_image(b"fake-png-bytes", "png")

        assert mock_client.chat.completions.create.call_count == expected_attempts


def test_extract_text_from_image_rejects_empty_bytes():
    with pytest.raises(ValueError):
        extract_text_from_image(b"", "png")


def test_extract_text_from_image_raises_when_ocr_disabled(monkeypatch):
    monkeypatch.setattr(config, "OCR_ENABLED", False)
    with pytest.raises(RuntimeError, match="未启用"):
        extract_text_from_image(b"fake-png-bytes", "png")


def _make_test_client() -> TestClient:
    from api.server import app

    return TestClient(app)




_INTERNAL_HEADERS = {"X-Internal-Token": config.INTERNAL_SERVICE_TOKEN}


def test_ocr_resume_endpoint_returns_text_on_success():
    client = _make_test_client()
    with patch("ocr.resume_ocr.extract_text_from_image", return_value="识别出的简历文本"):
        payload = {"image_base64": base64.b64encode(b"fake-png-bytes").decode(), "image_ext": "png"}
        response = client.post("/api/internal/ocr-resume", json=payload, headers=_INTERNAL_HEADERS)

    assert response.status_code == 200
    assert response.json() == {"text": "识别出的简历文本"}


def test_ocr_resume_endpoint_rejects_missing_internal_token():
    client = _make_test_client()
    payload = {"image_base64": base64.b64encode(b"fake-png-bytes").decode(), "image_ext": "png"}
    response = client.post("/api/internal/ocr-resume", json=payload)
    assert response.status_code == 401


def test_ocr_resume_endpoint_rejects_invalid_base64():
    client = _make_test_client()
    response = client.post(
        "/api/internal/ocr-resume",
        json={"image_base64": "not-valid-base64!!", "image_ext": "png"},
        headers=_INTERNAL_HEADERS,
    )
    assert response.status_code == 400


def test_ocr_resume_endpoint_returns_503_when_ocr_fails():
    client = _make_test_client()
    with patch("ocr.resume_ocr.extract_text_from_image", side_effect=RuntimeError("识别失败")):
        payload = {"image_base64": base64.b64encode(b"fake-png-bytes").decode(), "image_ext": "png"}
        response = client.post("/api/internal/ocr-resume", json=payload, headers=_INTERNAL_HEADERS)

    assert response.status_code == 503

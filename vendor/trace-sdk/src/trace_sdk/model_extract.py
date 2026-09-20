"""模型名/模型参数提取（对齐 langfuse _extract_model_name 4 层逻辑）。

§5.7:
  1. vendor id 路径表（ChatOpenAI / AzureChatOpenAI / Bedrock / ChatAnthropic / Ollama / ...）
  2. AzureOpenAI deployment 特殊处理
  3. repr 正则（Anthropic / Ollama / VLLM / ...）
  4. 兜底：kwargs.model_name → kwargs.model → invocation_params.model_name → invocation_params.model

另移植 langfuse `_parse_model_parameters` 提取 temperature/max_tokens 等参数。
"""
from __future__ import annotations

import re
from typing import Any, Optional


# ---- 第 1 层：vendor id 路径表 ----
_MODELS_BY_ID: list[tuple[str, list[str], str]] = [
    ("ChatGoogleGenerativeAI", ["kwargs", "model"], "serialized"),
    ("ChatMistralAI", ["kwargs", "model"], "serialized"),
    ("ChatVertexAi", ["kwargs", "model_name"], "serialized"),
    ("ChatVertexAI", ["kwargs", "model_name"], "serialized"),
    ("OpenAI", ["invocation_params", "model_name"], "kwargs"),
    ("ChatOpenAI", ["invocation_params", "model_name"], "kwargs"),
    ("AzureChatOpenAI", ["invocation_params", "model"], "kwargs"),
    ("AzureChatOpenAI", ["invocation_params", "model_name"], "kwargs"),
    ("AzureChatOpenAI", ["invocation_params", "azure_deployment"], "kwargs"),
    ("HuggingFacePipeline", ["invocation_params", "model_id"], "kwargs"),
    ("BedrockChat", ["kwargs", "model_id"], "serialized"),
    ("Bedrock", ["kwargs", "model_id"], "serialized"),
    ("BedrockLLM", ["kwargs", "model_id"], "serialized"),
    ("ChatBedrock", ["kwargs", "model_id"], "serialized"),
    ("LlamaCpp", ["invocation_params", "model_path"], "kwargs"),
    ("WatsonxLLM", ["invocation_params", "model_id"], "kwargs"),
]

# ---- 第 3 层：repr 正则 ----
_MODELS_BY_PATTERN: list[tuple[str, str, Optional[str]]] = [
    ("Anthropic", "model", "anthropic"),
    ("ChatAnthropic", "model", None),
    ("ChatTongyi", "model_name", None),
    ("ChatCohere", "model", None),
    ("Cohere", "model", None),
    ("HuggingFaceHub", "model", None),
    ("ChatAnyscale", "model_name", None),
    ("TextGen", "model", "text-gen"),
    ("Ollama", "model", None),
    ("OllamaLLM", "model", None),
    ("ChatOllama", "model", None),
    ("ChatFireworks", "model", None),
    ("ChatPerplexity", "model", None),
    ("VLLM", "model", None),
    ("Xinference", "model_uid", None),
    ("ChatOCIGenAI", "model_id", None),
    ("DeepInfra", "model_id", None),
]


def _extract_model_by_path(
    serialized: Optional[dict[str, Any]],
    kwargs: dict[str, Any],
    keys: list[str],
    select_from: str,
) -> Optional[str]:
    if serialized is None and select_from == "serialized":
        return None
    current_obj: Any = kwargs if select_from == "kwargs" else serialized
    for key in keys:
        if current_obj and isinstance(current_obj, dict):
            current_obj = current_obj.get(key)
        else:
            return None
        if not current_obj:
            return None
    return str(current_obj) if current_obj else None


def _extract_model_by_path_for_id(
    id_: str,
    serialized: Optional[dict[str, Any]],
    kwargs: dict[str, Any],
    keys: list[str],
    select_from: str,
) -> Optional[str]:
    if serialized is None:
        return None
    serialized_id = serialized.get("id")
    if (
        serialized_id
        and isinstance(serialized_id, list)
        and len(serialized_id) > 0
        and serialized_id[-1] == id_
    ):
        result = _extract_model_by_path(serialized, kwargs, keys, select_from)
        return str(result) if result is not None else None
    return None


def _extract_model_with_regex(pattern: str, text: str) -> Optional[str]:
    match = re.search(rf"{pattern}='(.*?)'", text)
    if match:
        return match.group(1)
    return None


def _extract_model_from_repr_by_pattern(
    id_: str,
    serialized: Optional[dict[str, Any]],
    pattern: str,
    default: Optional[str] = None,
) -> Optional[str]:
    if serialized is None:
        return None
    serialized_id = serialized.get("id")
    if (
        serialized_id
        and isinstance(serialized_id, list)
        and len(serialized_id) > 0
        and serialized_id[-1] == id_
    ):
        repr_str = serialized.get("repr")
        if repr_str and isinstance(repr_str, str):
            extracted = _extract_model_with_regex(pattern, repr_str)
            return extracted if extracted else default if default else None
    return None


def extract_model_name(
    serialized: Optional[dict[str, Any]] = None,
    **kwargs: Any,
) -> Optional[str]:
    """提取模型名（4 层策略，对齐 langfuse _extract_model_name）。

    优先检查 metadata 中的 ls_model_name（langfuse _parse_model_name_from_metadata）。
    """
    # 0. metadata ls_model_name（langchain 1.0+ 内置）
    metadata = kwargs.get("metadata")
    if isinstance(metadata, dict):
        ls_model = metadata.get("ls_model_name")
        if ls_model:
            return str(ls_model)

    # 1. vendor id 路径表
    for model_name, keys, select_from in _MODELS_BY_ID:
        model = _extract_model_by_path_for_id(
            model_name, serialized, kwargs, keys, select_from
        )
        if model:
            return model

    # 2. AzureOpenAI deployment 特殊处理
    if serialized:
        serialized_id = serialized.get("id")
        if (
            serialized_id
            and isinstance(serialized_id, list)
            and len(serialized_id) > 0
            and serialized_id[-1] == "AzureOpenAI"
        ):
            invocation_params = kwargs.get("invocation_params")
            if invocation_params and isinstance(invocation_params, dict):
                if invocation_params.get("model"):
                    return str(invocation_params.get("model"))
                if invocation_params.get("model_name"):
                    return str(invocation_params.get("model_name"))

            deployment_name = None
            deployment_version = None
            serialized_kwargs = serialized.get("kwargs")
            if serialized_kwargs and isinstance(serialized_kwargs, dict):
                if serialized_kwargs.get("openai_api_version"):
                    deployment_version = serialized_kwargs.get("deployment_version")
                if serialized_kwargs.get("deployment_name"):
                    deployment_name = serialized_kwargs.get("deployment_name")

            if not isinstance(deployment_name, str):
                return None
            if not isinstance(deployment_version, str):
                return deployment_name
            return (
                deployment_name + "-" + deployment_version
                if deployment_version not in deployment_name
                else deployment_name
            )

    # 3. repr 正则
    for model_name, pattern, default in _MODELS_BY_PATTERN:
        model = _extract_model_from_repr_by_pattern(
            model_name, serialized, pattern, default
        )
        if model:
            return model

    # 4. 兜底：select 已指定来源，路径只需键名（不重复嵌套 kwargs/invocation_params）
    fallback_paths = [
        ["model_name"],
        ["model"],
    ]
    for select in ["kwargs", "serialized"]:
        for path in fallback_paths:
            model = _extract_model_by_path(serialized, kwargs, path, select)
            if model:
                return str(model)

    return None


def parse_model_parameters(kwargs: dict[str, Any]) -> dict[str, Any]:
    """提取模型参数（对齐 langfuse _parse_model_parameters）。

    从 invocation_params 中提取 temperature/max_tokens/top_p 等参数。
    """
    invocation_params = kwargs.get("invocation_params")
    if not invocation_params or not isinstance(invocation_params, dict):
        return {}

    # IBM watsonx.ai 特殊处理
    if invocation_params.get("_type") == "IBM watsonx.ai" and invocation_params.get("params"):
        invocation_params = {
            **invocation_params,
            **invocation_params["params"],
        }
        del invocation_params["params"]

    return {
        key: value
        for key, value in {
            "temperature": invocation_params.get("temperature"),
            "max_tokens": invocation_params.get("max_tokens"),
            "max_completion_tokens": invocation_params.get("max_completion_tokens"),
            "top_p": invocation_params.get("top_p"),
            "frequency_penalty": invocation_params.get("frequency_penalty"),
            "presence_penalty": invocation_params.get("presence_penalty"),
            "request_timeout": invocation_params.get("request_timeout"),
            "decoding_method": invocation_params.get("decoding_method"),
            "min_new_tokens": invocation_params.get("min_new_tokens"),
            "max_new_tokens": invocation_params.get("max_new_tokens"),
            "stop_sequences": invocation_params.get("stop_sequences"),
        }.items()
        if value is not None
    }


__all__ = ["extract_model_name", "parse_model_parameters"]

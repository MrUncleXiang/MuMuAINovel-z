"""本书审查配置：默认值与读写辅助（供生成链、卷检查共用）"""
import json
from typing import Any, Dict


DEFAULT_REVIEW_CONFIG: Dict[str, Any] = {
    "enabled": True,      # 生成后自动审查开关
    "steps": 3,           # 流水线步数：1=错别字，2=+表达/AI味，3=+剧情
    "max_rounds": 2,      # 每章最多修改轮数（超了停下等人工）
}


def review_config_defaults(raw: str | None) -> Dict[str, Any]:
    """读取配置（缺省字段用默认值补齐）"""
    cfg = dict(DEFAULT_REVIEW_CONFIG)
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                cfg.update(data)
        except Exception:
            pass
    # 取值约束
    cfg["enabled"] = bool(cfg.get("enabled", True))
    cfg["steps"] = max(1, min(3, int(cfg.get("steps", 3) or 3)))
    cfg["max_rounds"] = max(1, min(3, int(cfg.get("max_rounds", 2) or 2)))
    return cfg

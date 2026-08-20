from __future__ import annotations

import json
import logging
from pathlib import Path

import yaml

from .schema import VoiceModel

LOG = logging.getLogger(__name__)


class ModelRegistry:
    def __init__(self, weights_root: Path):
        self.weights_root = weights_root

    def scan(self, engine: str | None = None) -> list[VoiceModel]:
        engines = [engine] if engine in {"rvc", "ddsp"} else ["rvc", "ddsp"]
        models: list[VoiceModel] = []
        overrides = self._inference_overrides()
        for current in engines:
            for group, bundled in (("bundled", True), ("user_models", False)):
                base = self.weights_root / current / group
                if not base.exists():
                    continue
                for meta in base.glob("*/model.json"):
                    try:
                        data = json.loads(meta.read_text(encoding="utf-8"))
                        data.setdefault("bundled", bundled)
                        model_id = str(data.get("id", ""))
                        if isinstance(overrides.get(model_id), dict):
                            data.update(overrides[model_id])
                        model = VoiceModel.model_validate(data)
                        if all((meta.parent / item).is_file() for item in model.model_files):
                            models.append(model)
                    except (OSError, ValueError) as exc:
                        LOG.warning("忽略损坏的模型元数据 %s: %s", meta, exc)
        return sorted(models, key=lambda m: (not m.featured, m.sort_order, m.display_name.casefold()))

    def selectable(self, engine: str | None = None) -> list[VoiceModel]:
        """Return only voices allowed in new conversion jobs."""
        return [model for model in self.scan(engine) if model.selectable and model.quality_status != "rejected"]

    def _inference_overrides(self) -> dict[str, object]:
        path = self.weights_root.parent / "config" / "model_inference_overrides.yaml"
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError, yaml.YAMLError) as exc:
            LOG.warning("忽略损坏的模型推理覆盖配置 %s: %s", path, exc)
            return {}

    def get(self, model_id: str) -> VoiceModel | None:
        return next((model for model in self.scan() if model.id == model_id), None)

    def hashes(self) -> set[str]:
        return {digest for model in self.scan() for digest in model.sha256.values()}

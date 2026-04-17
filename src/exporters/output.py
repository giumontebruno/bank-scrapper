from __future__ import annotations

import csv
import json
from pathlib import Path

from query.repository import PromotionRepository


def export_promotions(repository: PromotionRepository, format: str) -> Path:
    promotions = [json.loads(item.json()) for item in repository.list_promotions()]
    output_dir = Path("data/processed")
    output_dir.mkdir(parents=True, exist_ok=True)

    if format == "json":
        path = output_dir / "promos_export.json"
        path.write_text(json.dumps(promotions, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
    if format == "csv":
        path = output_dir / "promos_export.csv"
        if promotions:
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(promotions[0].keys()))
                writer.writeheader()
                writer.writerows(promotions)
        else:
            path.write_text("", encoding="utf-8")
        return path
    raise ValueError(f"Formato no soportado: {format}")

thonimport csv
import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

import pandas as pd
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

class DataExporter:
    """
    Export scraped jobs into various formats: JSON, CSV, Excel, XML.
    """

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        logger.debug("DataExporter will write files into %s", self.output_dir)

    def export(self, data: Sequence[Dict[str, Any]], fmt: str, file_prefix: str) -> Path:
        if not data:
            raise ValueError("No data supplied for export.")

        fmt_lower = fmt.lower()
        if fmt_lower not in {"json", "csv", "excel", "xml"}:
            raise ValueError(f"Unsupported export format: {fmt}")

        if fmt_lower == "json":
            return self._export_json(data, file_prefix)
        if fmt_lower == "csv":
            return self._export_csv(data, file_prefix)
        if fmt_lower == "excel":
            return self._export_excel(data, file_prefix)
        if fmt_lower == "xml":
            return self._export_xml(data, file_prefix)

        # This should not be reached.
        raise RuntimeError(f"Unhandled export format: {fmt_lower}")

    def _export_json(self, data: Sequence[Dict[str, Any]], file_prefix: str) -> Path:
        path = self.output_dir / f"{file_prefix}.json"
        with path.open("w", encoding="utf-8") as f:
            json.dump(list(data), f, ensure_ascii=False, indent=2)
        logger.info("Wrote JSON output to %s", path)
        return path

    def _export_csv(self, data: Sequence[Dict[str, Any]], file_prefix: str) -> Path:
        path = self.output_dir / f"{file_prefix}.csv"
        fieldnames = self._collect_fieldnames(data)

        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for item in data:
                row = {k: self._scalar_or_join(item.get(k)) for k in fieldnames}
                writer.writerow(row)

        logger.info("Wrote CSV output to %s", path)
        return path

    def _export_excel(self, data: Sequence[Dict[str, Any]], file_prefix: str) -> Path:
        path = self.output_dir / f"{file_prefix}.xlsx"
        # Flatten sequences for Excel columns.
        flattened: List[Dict[str, Any]] = []
        for item in data:
            flattened.append(
                {k: self._scalar_or_join(v) for k, v in item.items()}
            )

        df = pd.DataFrame(flattened)
        df.to_excel(path, index=False)
        logger.info("Wrote Excel output to %s", path)
        return path

    def _export_xml(self, data: Sequence[Dict[str, Any]], file_prefix: str) -> Path:
        root = ET.Element("jobs")

        for item in data:
            job_el = ET.SubElement(root, "job")
            for key, value in item.items():
                child = ET.SubElement(job_el, key)
                child.text = self._scalar_or_join(value)

        tree = ET.ElementTree(root)
        path = self.output_dir / f"{file_prefix}.xml"
        tree.write(path, encoding="utf-8", xml_declaration=True)
        logger.info("Wrote XML output to %s", path)
        return path

    @staticmethod
    def _collect_fieldnames(data: Sequence[Dict[str, Any]]) -> List[str]:
        fields = set()
        for item in data:
            fields.update(item.keys())
        # Keep deterministic order, moving common fields first.
        preferred_order = [
            "jobId",
            "title",
            "description",
            "createdAt",
            "jobType",
            "duration",
            "budget",
            "clientLocation",
            "clientPaymentVerification",
            "clientSpent",
            "clientReviews",
            "category",
            "skills",
        ]
        ordered: List[str] = []
        for field in preferred_order:
            if field in fields:
                ordered.append(field)
                fields.remove(field)
        ordered.extend(sorted(fields))
        return ordered

    @staticmethod
    def _scalar_or_join(value: Any) -> str:
        """
        Convert any value into a string suitable for flat output.

        Lists/tuples are joined with comma and space.
        """
        if value is None:
            return ""
        if isinstance(value, (list, tuple, set)):
            return ", ".join(str(v) for v in value)
        return str(value)
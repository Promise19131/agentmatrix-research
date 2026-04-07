import datetime
import importlib.util
import json
import os
import re
import tempfile
import uuid
from pathlib import Path

try:
    import PyPDF2
except ImportError:
    PyPDF2 = None

try:
    from docx import Document
except ImportError:
    Document = None

from .mineru_runtime import mineru_runtime
from common.paths import runtime_path


class DocumentNormalizerService:
    def __init__(self, project_root):
        self.project_root = Path(project_root)
        self.base_dir = runtime_path("document_normalizer")
        self.upload_dir = self.base_dir / "uploads"
        self.output_dir = self.base_dir / "normalized_documents"
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def engine_status(self):
        mineru_status = mineru_runtime.status()
        return {
            "auto": {
                "available": True,
                "label": "Auto Route",
                "detail": "优先走 MinerU，其次 Docling，最后回退 PyPDF2。"
            },
            "mineru": {
                "available": bool(mineru_status.get("mineru_cli")),
                "label": "MinerU",
                "detail": "复杂论文、研报和图文混排 PDF 优先引擎。"
            },
            "docling": {
                "available": self._is_docling_available(),
                "label": "Docling",
                "detail": "通用 PDF 转换引擎。"
            },
            "pypdf2": {
                "available": PyPDF2 is not None,
                "label": "PyPDF2",
                "detail": "文本层 PDF 的可靠回退引擎。"
            }
        }

    def normalize_upload(self, file_storage, user_id=None, preferred_engine="auto"):
        original_name = file_storage.filename or "document"
        extension = Path(original_name).suffix.lower()
        job_id = f"dn_{uuid.uuid4().hex[:12]}"
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", original_name)
        upload_path = self.upload_dir / f"{job_id}_{safe_name}"
        file_storage.save(upload_path)

        extracted = self._extract(upload_path, original_name, extension, preferred_engine)
        normalized_text = self._normalize_text(extracted["text"])
        outline = self._build_outline(normalized_text)
        route_hints = self._infer_route_hints(original_name, normalized_text, extension)
        completion = self._assess_completion(extension, normalized_text, extracted["warnings"], extracted["extractor"], extracted.get("engine_selected"))
        evaluation = self._build_evaluation(extension, original_name, normalized_text, outline, extracted, completion, route_hints)
        downloads = self._persist_outputs(job_id, original_name, extension, normalized_text, outline, extracted, completion, evaluation, route_hints, preferred_engine, user_id)
        return {
            "job_id": job_id,
            "agent": {
                "id": "document-normalizer-agent",
                "name": "Multi-Format Document Normalizer Agent"
            },
            "engine": {
                "requested": preferred_engine,
                "selected": extracted.get("engine_selected"),
                "candidates": extracted.get("engine_candidates", []),
                "attempts": extracted.get("engine_attempts", []),
                "availability": self.engine_status()
            },
            "file": {
                "original_name": original_name,
                "extension": extension,
                "size_bytes": upload_path.stat().st_size
            },
            "extraction": {
                "extractor": extracted["extractor"],
                "character_count": len(normalized_text),
                "section_count": len(outline),
                "table_count": extracted.get("table_count", 0),
                "warnings": extracted["warnings"]
            },
            "completion": completion,
            "evaluation": evaluation,
            "route_hints": route_hints,
            "preview_markdown": self._compose_markdown(original_name, extension, normalized_text, outline, extracted, completion, route_hints),
            "downloads": downloads
        }

    def result_file(self, job_id, kind):
        target_dir = self.output_dir / job_id
        mapping = {
            "markdown": target_dir / "clean.md",
            "structured": target_dir / "structured.json",
            "meta": target_dir / "meta.json"
        }
        candidate = mapping.get(kind)
        if candidate and candidate.exists():
            return candidate
        return None

    def _extract(self, file_path, original_name, extension, preferred_engine):
        if extension == ".pdf":
            return self._extract_pdf(file_path, original_name, preferred_engine)
        if extension in {".md", ".txt"}:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
            return self._success_result(text, "plain-text", "native-text")
        if extension == ".docx":
            return self._extract_docx(file_path)
        return {
            "text": "",
            "extractor": "unsupported",
            "warnings": [f"Unsupported file type: {extension}"],
            "table_count": 0,
            "engine_selected": "unsupported",
            "engine_candidates": [],
            "engine_attempts": []
        }

    def _extract_pdf(self, file_path, original_name, preferred_engine):
        engine_order = self._resolve_pdf_engine_order(original_name, preferred_engine)
        attempts = []
        collected_warnings = []
        best_result = None
        for engine_name in engine_order:
            if engine_name == "mineru":
                result = self._extract_pdf_with_mineru(file_path)
            elif engine_name == "docling":
                result = self._extract_pdf_with_docling(file_path)
            else:
                result = self._extract_pdf_with_pypdf2(file_path)

            text = (result.get("text") or "").strip()
            warnings = list(result.get("warnings", []))
            if text:
                attempts.append({"engine": engine_name, "status": "success", "character_count": len(text)})
                result["warnings"] = collected_warnings + warnings
                result["engine_selected"] = engine_name
                result["engine_candidates"] = engine_order
                result["engine_attempts"] = attempts
                return result

            attempts.append({"engine": engine_name, "status": "failed", "reason": warnings[0] if warnings else f"{engine_name} produced empty output."})
            collected_warnings.extend(warnings or [f"{engine_name} produced empty output."])
            best_result = result

        return {
            "text": "",
            "extractor": best_result.get("extractor", "pdf-failed") if best_result else "pdf-failed",
            "warnings": collected_warnings or ["No PDF extraction engine produced usable output."],
            "table_count": 0,
            "engine_selected": engine_order[-1] if engine_order else "unknown",
            "engine_candidates": engine_order,
            "engine_attempts": attempts
        }

    def _extract_pdf_with_mineru(self, file_path):
        status = mineru_runtime.status()
        if not status.get("mineru_cli"):
            return {
                "text": "",
                "extractor": "mineru-unavailable",
                "warnings": ["MinerU CLI is not available in the current runtime."],
                "table_count": 0,
                "engine_selected": "mineru"
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            result = mineru_runtime.run_parse(str(file_path), temp_dir)
            markdown_path = result.get("markdown_path")
            if result.get("success") and markdown_path and Path(markdown_path).exists():
                text = Path(markdown_path).read_text(encoding="utf-8", errors="ignore")
                return {
                    "text": text,
                    "extractor": "mineru-cli",
                    "warnings": [],
                    "table_count": text.count("<table>") + text.count("| ---"),
                    "engine_selected": "mineru"
                }
            warnings = []
            if result.get("stderr"):
                warnings.append(result["stderr"].strip()[:1000])
            if result.get("stdout"):
                warnings.append(result["stdout"].strip()[:1000])
            if not warnings:
                warnings.append("MinerU did not produce a markdown output file.")
            return {
                "text": "",
                "extractor": "mineru-cli-error",
                "warnings": warnings,
                "table_count": 0,
                "engine_selected": "mineru"
            }

    def _extract_pdf_with_docling(self, file_path):
        if not self._is_docling_available():
            return {
                "text": "",
                "extractor": "docling-unavailable",
                "warnings": ["Docling is not installed in the current runtime."],
                "table_count": 0,
                "engine_selected": "docling"
            }
        try:
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            from docling.document_converter import DocumentConverter, PdfFormatOption

            artifacts_path = self.base_dir / ".cache" / "docling" / "models"
            artifacts_path.mkdir(parents=True, exist_ok=True)
            os.environ.setdefault("DOCLING_ARTIFACTS_PATH", str(artifacts_path))
            pipeline_options = PdfPipelineOptions(artifacts_path=str(artifacts_path))
            converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)})
            result = converter.convert(str(file_path))
            document = getattr(result, "document", result)
            markdown = document.export_to_markdown() if hasattr(document, "export_to_markdown") else ""
            markdown = (markdown or "").strip()
            if markdown:
                return {
                    "text": markdown,
                    "extractor": "docling",
                    "warnings": [],
                    "table_count": markdown.count("| ---"),
                    "engine_selected": "docling"
                }
            return {
                "text": "",
                "extractor": "docling-empty",
                "warnings": ["Docling returned an empty markdown payload."],
                "table_count": 0,
                "engine_selected": "docling"
            }
        except Exception as error:
            return {
                "text": "",
                "extractor": "docling-error",
                "warnings": [f"Docling conversion failed: {error}"],
                "table_count": 0,
                "engine_selected": "docling"
            }

    def _extract_pdf_with_pypdf2(self, file_path):
        if PyPDF2 is None:
            return {
                "text": "",
                "extractor": "pypdf2-unavailable",
                "warnings": ["PyPDF2 is not installed in the current runtime."],
                "table_count": 0,
                "engine_selected": "pypdf2"
            }
        pages = []
        warnings = []
        with open(file_path, "rb") as file_obj:
            reader = PyPDF2.PdfReader(file_obj)
            for index, page in enumerate(reader.pages, start=1):
                page_text = page.extract_text() or ""
                if page_text.strip():
                    pages.append(f"# Page {index}\n{page_text.strip()}")
                else:
                    warnings.append(f"Page {index} produced little or no extractable text.")
        return {
            "text": "\n\n".join(pages),
            "extractor": "pypdf2",
            "warnings": warnings,
            "table_count": 0,
            "engine_selected": "pypdf2"
        }

    def _extract_docx(self, file_path):
        if Document is None:
            return {
                "text": "",
                "extractor": "docx-unavailable",
                "warnings": ["python-docx is not installed in the current runtime."],
                "table_count": 0,
                "engine_selected": "python-docx",
                "engine_candidates": ["python-docx"],
                "engine_attempts": [{"engine": "python-docx", "status": "failed", "reason": "python-docx is not installed in the current runtime."}]
            }
        doc = Document(str(file_path))
        blocks = [paragraph.text.strip() for paragraph in doc.paragraphs if paragraph.text.strip()]
        text = "\n\n".join(blocks)
        return self._success_result(text, "python-docx", "python-docx")

    def _success_result(self, text, extractor, engine_name):
        return {
            "text": text,
            "extractor": extractor,
            "warnings": [],
            "table_count": text.count("| ---"),
            "engine_selected": engine_name,
            "engine_candidates": [engine_name],
            "engine_attempts": [{"engine": engine_name, "status": "success", "character_count": len(text)}]
        }

    def _normalize_text(self, text):
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _build_outline(self, text):
        outline = []
        for line in text.splitlines():
            candidate = line.strip()
            if not candidate:
                continue
            if candidate.startswith("#"):
                outline.append(candidate.lstrip("# ").strip())
            elif len(candidate) < 90 and any(marker in candidate.lower() for marker in ["abstract", "introduction", "conclusion", "appendix", "page "]):
                outline.append(candidate)
            if len(outline) >= 18:
                break
        return outline or ["Overview"]

    def _infer_route_hints(self, original_name, text, extension):
        source = f"{original_name}\n{text[:6000]}".lower()
        hints = []
        if any(token in source for token in ["abstract", "methodology", "references", "appendix", "p-value", "paper"]):
            hints.append("paper-reproduction-agent")
        if any(token in source for token in ["market outlook", "coverage", "portfolio", "strategy", "signal", "factor"]):
            hints.append("strategy-signal-agent")
        if not hints:
            hints.append("general-analysis-agent")
        return hints[:3]

    def _assess_completion(self, extension, normalized_text, warnings, extractor, engine):
        length = len(normalized_text)
        base_score = 45
        if extension == ".pdf":
            base_score = 78 if engine == "mineru" else 72 if engine == "docling" else 68
        elif extension == ".docx":
            base_score = 84
        elif extension in {".md", ".txt"}:
            base_score = 90
        if length >= 50000:
            base_score += 12
        elif length >= 25000:
            base_score += 8
        elif length >= 8000:
            base_score += 4
        score = max(10, min(98, base_score - min(len(warnings) * 4, 20)))
        if score >= 85:
            label = "strong"
        elif score >= 70:
            label = "usable"
        elif score >= 50:
            label = "partial"
        else:
            label = "limited"
        reason = "结果已经可用。" if not warnings else "结果可用，但检测到需要人工复核的提取警告。"
        return {"score": score, "label": label, "reason": reason}

    def _build_evaluation(self, extension, original_name, normalized_text, outline, extracted, completion, route_hints):
        source = normalized_text.lower()
        warning_count = len(extracted.get("warnings", []))
        character_count = len(normalized_text)
        section_count = len(outline)
        engine = extracted.get("engine_selected") or extracted.get("extractor")
        heading_count = normalized_text.count("\n#") + (1 if normalized_text.startswith("#") else 0)
        complex_markers = sum(source.count(token) for token in ["table", "figure", "equation", "appendix", "chart", "图", "表", "公式"])

        completeness = 5 if character_count >= 50000 else 4 if character_count >= 25000 else 3 if character_count >= 8000 else 2 if character_count >= 1500 else 1
        structure = 5 if section_count >= 12 and heading_count >= 10 else 4 if section_count >= 8 else 3 if section_count >= 4 else 2
        complex_objects = 5 if engine == "mineru" else 4 if engine == "docling" else 2
        if complex_markers >= 8 and engine == "pypdf2":
            complex_objects = 1
        downstream = 5 if completion["score"] >= 85 else 4 if completion["score"] >= 70 else 3 if completion["score"] >= 55 else 2
        revision = 5 - min(4, warning_count)
        revision = max(1, revision)
        dimensions = [
            {"id": "content_completeness", "label": "内容完整度", "score": completeness, "max_score": 5, "reason": f"当前抽取出约 {character_count:,} 个字符，并识别出 {section_count} 个章节线索。"},
            {"id": "structure_fidelity", "label": "结构保真度", "score": structure, "max_score": 5, "reason": f"大纲条目 {section_count} 个，Markdown 标题标记约 {heading_count} 处。"},
            {"id": "complex_object_retention", "label": "复杂对象保留度", "score": complex_objects, "max_score": 5, "reason": f"当前引擎为 {engine}，复杂对象标记约 {complex_markers} 处。"},
            {"id": "downstream_utility", "label": "下游可用性", "score": downstream, "max_score": 5, "reason": f"当前给出 {len(route_hints)} 个后续 Agent 建议，完成度为 {completion['score']}%。"},
            {"id": "human_revision_cost", "label": "人工修正成本", "score": revision, "max_score": 5, "reason": f"当前警告数为 {warning_count}。该项分数越高，代表人工修正成本越低。"},
        ]
        total_score = sum(item["score"] for item in dimensions)
        if total_score >= 21:
            verdict = {"level": "high_quality", "label": "高质量，可直接进入后续 Agent", "recommended_for_downstream": True, "reason": "当前结果在结构、完整度和可用性方面表现较强。"}
        elif total_score >= 16:
            verdict = {"level": "usable_with_light_review", "label": "可用，建议少量人工复核后进入后续 Agent", "recommended_for_downstream": True, "reason": "当前结果已经可用，但建议重点检查图表、公式和页内布局。"}
        elif total_score >= 11:
            verdict = {"level": "draft_only", "label": "仅适合作为草稿输入", "recommended_for_downstream": False, "reason": "当前结果可以做草稿输入，但不建议直接进入高要求链路。"}
        else:
            verdict = {"level": "not_recommended", "label": "当前不建议继续下游处理", "recommended_for_downstream": False, "reason": "当前抽取质量不足，建议更换引擎或补充人工整理。"}
        return {
            "dimensions": dimensions,
            "total_score": total_score,
            "max_total_score": 25,
            "summary": {"headline": "五维评测面板", "short_verdict": verdict["label"]},
            "verdict": verdict,
            "document_profile": self._infer_document_profile(original_name, normalized_text, extension)
        }

    def _infer_document_profile(self, original_name, normalized_text, extension):
        if extension != ".pdf":
            return "general"
        source = f"{original_name}\n{normalized_text[:8000]}".lower()
        if any(token in source for token in ["abstract", "methodology", "references", "p-value", "paper"]):
            return "paper"
        if any(token in source for token in ["outlook", "coverage", "portfolio", "investment", "allocation"]):
            return "report"
        return "general"

    def _compose_markdown(self, original_name, extension, normalized_text, outline, extracted, completion, route_hints):
        overview = [
            "# AI-Ready Document Package",
            "",
            "## Overview",
            f"- Original file: {original_name}",
            f"- File type: {extension}",
            f"- Extractor: {extracted['extractor']}",
            f"- Completion score: {completion['score']}%",
            f"- Completion label: {completion['label']}",
            f"- Recommended next agents: {', '.join(route_hints)}",
            "",
            "## Extraction Warnings",
        ]
        warnings = extracted["warnings"] or ["No major warnings detected."]
        warning_lines = [f"- {item}" for item in warnings]
        outline_lines = ["", "## Outline"] + [f"- {item}" for item in outline[:18]]
        body = ["", "## Normalized Text", "", normalized_text[:16000]]
        return "\n".join(overview + warning_lines + outline_lines + body)

    def _persist_outputs(self, job_id, original_name, extension, normalized_text, outline, extracted, completion, evaluation, route_hints, preferred_engine, user_id):
        target_dir = self.output_dir / job_id
        target_dir.mkdir(parents=True, exist_ok=True)
        clean_path = target_dir / "clean.md"
        structured_path = target_dir / "structured.json"
        meta_path = target_dir / "meta.json"
        clean_path.write_text(self._compose_markdown(original_name, extension, normalized_text, outline, extracted, completion, route_hints), encoding="utf-8")
        structured_payload = {
            "job_id": job_id,
            "original_name": original_name,
            "extension": extension,
            "normalized_text": normalized_text,
            "outline": outline,
            "route_hints": route_hints,
            "completion": completion,
            "evaluation": evaluation,
            "extraction": {
                "extractor": extracted["extractor"],
                "warnings": extracted["warnings"],
                "table_count": extracted.get("table_count", 0),
                "engine_selected": extracted.get("engine_selected"),
                "engine_attempts": extracted.get("engine_attempts", [])
            }
        }
        structured_path.write_text(json.dumps(structured_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        meta_payload = {
            "job_id": job_id,
            "created_at": datetime.datetime.utcnow().isoformat() + "Z",
            "user_id": user_id,
            "original_name": original_name,
            "extension": extension,
            "character_count": len(normalized_text),
            "route_hints": route_hints,
            "completion": completion,
            "evaluation": evaluation,
            "engine": {
                "requested": preferred_engine,
                "selected": extracted.get("engine_selected"),
                "attempts": extracted.get("engine_attempts", [])
            }
        }
        meta_path.write_text(json.dumps(meta_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "markdown": f"/api/agents/document-normalizer/result/{job_id}/markdown",
            "structured": f"/api/agents/document-normalizer/result/{job_id}/structured",
            "meta": f"/api/agents/document-normalizer/result/{job_id}/meta"
        }

    def _resolve_pdf_engine_order(self, original_name, preferred_engine):
        requested = (preferred_engine or "auto").lower()
        if requested in {"mineru", "docling", "pypdf2"}:
            return [requested] + [engine for engine in ["mineru", "docling", "pypdf2"] if engine != requested]
        profile = self._infer_document_profile(original_name, "", ".pdf")
        if profile in {"paper", "report"}:
            return ["mineru", "docling", "pypdf2"]
        return ["docling", "mineru", "pypdf2"]

    def _is_docling_available(self):
        return importlib.util.find_spec("docling") is not None


document_normalizer_service = DocumentNormalizerService(project_root=Path(__file__).resolve().parents[3])

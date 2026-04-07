import argparse
import json
import os
from pathlib import Path

import requests


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--api-url", default="http://127.0.0.1:8018/file_parse")
    parser.add_argument("--lang", default="en")
    parser.add_argument("--backend", default="pipeline")
    parser.add_argument("--method", default="txt")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--work-dir", default="")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    work_dir = args.work_dir or str(pdf_path.parent / "mineru_smoketest_output")
    os.makedirs(work_dir, exist_ok=True)

    with open(pdf_path, "rb") as file_obj:
        response = requests.post(
            args.api_url,
            files=[("files", (pdf_path.name, file_obj, "application/pdf"))],
            data={
                "output_dir": work_dir,
                "lang_list": args.lang,
                "backend": args.backend,
                "parse_method": args.method,
                "formula_enable": "false",
                "table_enable": "true",
                "return_md": "true",
                "return_middle_json": "false",
                "return_model_output": "false",
                "return_content_list": "false",
                "return_images": "false",
            },
            timeout=1800,
        )

    payload = {
        "status_code": response.status_code,
        "content_type": response.headers.get("content-type"),
        "body_preview": response.text[:4000],
    }

    with open(args.output_json, "w", encoding="utf-8") as file_obj:
        json.dump(payload, file_obj, ensure_ascii=False, indent=2)

    print(args.output_json)


if __name__ == "__main__":
    main()

import argparse
import json
from pathlib import Path

import requests


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--engine", default="auto")
    parser.add_argument("--api-base", default="http://127.0.0.1:8005")
    parser.add_argument("--output-json", required=True)
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    with open(pdf_path, "rb") as file_obj:
        response = requests.post(
            f"{args.api_base}/api/agents/document-normalizer/normalize",
            data={"user_id": "api-test", "engine_preference": args.engine},
            files={"file": (pdf_path.name, file_obj, "application/pdf")},
            timeout=1800,
        )

    payload = response.json()
    summary = {
        "status_code": response.status_code,
        "engine_requested": args.engine,
        "engine_selected": payload.get("engine", {}).get("selected"),
        "attempts": payload.get("engine", {}).get("attempts"),
        "extractor": payload.get("extraction", {}).get("extractor"),
        "character_count": payload.get("extraction", {}).get("character_count"),
        "section_count": payload.get("extraction", {}).get("section_count"),
        "warning_count": len(payload.get("extraction", {}).get("warnings", [])),
        "completion": payload.get("completion"),
        "evaluation": {
            "total_score": payload.get("evaluation", {}).get("total_score"),
            "verdict": payload.get("evaluation", {}).get("verdict"),
        },
        "downloads": payload.get("downloads"),
    }
    Path(args.output_json).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output_json)


if __name__ == "__main__":
    main()

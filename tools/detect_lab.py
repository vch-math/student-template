import os
import re
import sys


def detect_lab() -> str:
    explicit = os.getenv("LAB")
    if explicit:
        return explicit.strip()

    branch = os.getenv("GITHUB_HEAD_REF") or os.getenv("GITHUB_REF_NAME") or ""
    match = re.search(r"lab[-_]?(\d+)", branch, flags=re.IGNORECASE)
    if match:
        return match.group(1)

    return ""


def main() -> int:
    lab = detect_lab()
    if not lab:
        print("Не удалось определить номер лабораторной. Укажите LAB=1.", file=sys.stderr)
        return 1

    output_path = os.getenv("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as handle:
            handle.write(f"lab={lab}\n")
    else:
        print(lab)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


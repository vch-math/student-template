import json
import os
import pathlib
import re
import subprocess
import sys
from typing import Dict, List, Tuple


ROOT = pathlib.Path(__file__).resolve().parents[1]
TESTS_ROOT = ROOT / "tests"
BUILD_ROOT = ROOT / ".build"


def read_manifest(lab: str) -> dict:
    manifest_path = TESTS_ROOT / f"lab-{lab}" / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Нет манифеста тестов: {manifest_path}")
    with manifest_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def detect_language(lab_dir: pathlib.Path) -> Tuple[str, pathlib.Path]:
    mapping = {
        "python": lab_dir / "main.py",
        "c": lab_dir / "main.c",
        "cpp": lab_dir / "main.cpp",
        "java": lab_dir / "Main.java",
        "go": lab_dir / "main.go",
    }
    for lang, path in mapping.items():
        if path.exists():
            return lang, path
    return "", pathlib.Path()


def compile_program(lang: str, source: pathlib.Path, build_dir: pathlib.Path) -> List[str]:
    build_dir.mkdir(parents=True, exist_ok=True)
    if lang == "python":
        return [sys.executable, str(source)]
    if lang == "c":
        output = build_dir / "main"
        subprocess.run(["gcc", str(source), "-O2", "-o", str(output)], check=True)
        return [str(output)]
    if lang == "cpp":
        output = build_dir / "main"
        subprocess.run(["g++", str(source), "-O2", "-o", str(output)], check=True)
        return [str(output)]
    if lang == "java":
        subprocess.run(["javac", str(source)], check=True, cwd=source.parent)
        return ["java", "-cp", str(source.parent), "Main"]
    if lang == "go":
        output = build_dir / "main"
        subprocess.run(["go", "build", "-o", str(output), str(source)], check=True)
        return [str(output)]

    run_cmd = os.getenv("RUN_CMD")
    if run_cmd:
        return run_cmd.split()

    raise RuntimeError("Не удалось определить язык. Добавьте main.py/main.c/main.cpp/Main.java.")


def run_test(cmd: List[str], input_data: bytes, timeout_sec: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        input=input_data,
        capture_output=True,
        timeout=timeout_sec,
        check=False,
    )


def normalize_text(value: str) -> str:
    return value.replace("\u2013", "-").replace("\u2014", "-").replace("\u2212", "-")


def extract_first_line(output_text: str) -> str:
    for line in output_text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def get_variant_selector(variant: Dict) -> str:
    selector = variant.get("selector")
    if isinstance(selector, str) and selector.strip():
        return selector.strip()
    out_contains = variant.get("out_contains")
    if isinstance(out_contains, list) and out_contains:
        first = out_contains[0]
        return first.strip() if isinstance(first, str) else str(first)
    if isinstance(out_contains, str) and out_contains.strip():
        return out_contains.strip()
    return ""


def format_expected(out_contains: List[str], out_regex: List[str], expected_solution) -> str:
    parts = []
    if out_contains:
        parts.append(f"Ожидаемые строки: {out_contains}")
    if out_regex:
        parts.append(f"Ожидаемые regex: {out_regex}")
    if expected_solution is not None:
        parts.append(f"Ожидаемое решение: {expected_solution}")
    return "\n".join(parts)


def check_contains(stdout: str, expected: List[str]) -> List[str]:
    missing = []
    normalized_stdout = normalize_text(stdout)
    for item in expected:
        normalized_item = normalize_text(item)
        if normalized_item not in normalized_stdout:
            missing.append(item)
    return missing


def check_regex(stdout: str, expected: List[str]) -> List[str]:
    missing = []
    normalized_stdout = normalize_text(stdout)
    for pattern in expected:
        if re.search(pattern, normalized_stdout) is None:
            missing.append(f"regex:{pattern}")
    return missing


def extract_solution(stdout: str) -> Dict[int, float]:
    values: Dict[int, float] = {}
    for match in re.finditer(
        r"x\s*\[\s*(\d+)\s*\]\s*=\s*([+-]?\d+(?:\.\d+)?(?:e[+-]?\d+)?)",
        stdout,
        flags=re.IGNORECASE,
    ):
        values[int(match.group(1))] = float(match.group(2))
    for match in re.finditer(
        r"x\s*(\d+)\s*=\s*([+-]?\d+(?:\.\d+)?(?:e[+-]?\d+)?)",
        stdout,
        flags=re.IGNORECASE,
    ):
        index = int(match.group(1))
        if index not in values:
            values[index] = float(match.group(2))
    return values


def check_solution(stdout: str, expected: List[float], tol: float) -> List[str]:
    missing = []
    found = extract_solution(stdout)
    if not found:
        return ["solution:not_found"]

    indices = sorted(found.keys())
    is_zero_based = 0 in indices

    for i, expected_value in enumerate(expected):
        key = i if is_zero_based else i + 1
        if key not in found:
            missing.append(f"solution:x{key}:not_found")
            continue
        actual = found[key]
        if abs(actual - expected_value) > tol:
            missing.append(f"solution:x{key}:expected≈{expected_value}")
    return missing


def parse_input_tolerance(input_text: str, default_tol: float) -> float:
    matches = re.findall(r"[+-]?\d+(?:\.\d+)?(?:e[+-]?\d+)?", input_text, flags=re.IGNORECASE)
    if not matches:
        return default_tol
    try:
        return float(matches[-1]) * 3
    except ValueError:
        return default_tol


def load_lines(path: pathlib.Path) -> List[str]:
    if not path.exists():
        raise FileNotFoundError(f"Файл не найден: {path}")
    with path.open("r", encoding="utf-8") as handle:
        return [line.strip() for line in handle.read().splitlines() if line.strip()]


def normalize_expected(value, base_dir: pathlib.Path) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        items = value
    else:
        items = [value]

    resolved: List[str] = []
    for item in items:
        if not isinstance(item, str):
            item = str(item)
        if item.endswith(".txt"):
            resolved.extend(load_lines(base_dir / item))
        else:
            resolved.append(item)
    return resolved


def resolve_input(test: Dict, input_dir: pathlib.Path) -> bytes:
    if "in" not in test:
        raise KeyError("В тесте нет поля 'in'")
    raw = test["in"]
    if not isinstance(raw, str):
        raw = str(raw)
    if raw.endswith(".txt"):
        path = input_dir / raw
        if not path.exists():
            raise FileNotFoundError(f"Входной файл не найден: {path}")
        return path.read_bytes()
    return raw.encode("utf-8")


def evaluate_variant(
    stdout: str,
    variant: Dict,
    input_text: str,
    default_tol: float,
) -> Tuple[bool, List[str]]:
    missing = []
    missing.extend(check_contains(stdout, variant.get("out_contains", [])))
    missing.extend(check_regex(stdout, variant.get("out_regex", [])))
    expected_solution = variant.get("expected_solution")
    if expected_solution is not None:
        if variant.get("use_input_tolerance"):
            scale = float(variant.get("tolerance_scale") or 1.0)
            tol = parse_input_tolerance(input_text, default_tol) * scale
        else:
            tol = float(variant.get("solution_tolerance", default_tol))
        missing.extend(check_solution(stdout, expected_solution, tol))
    return len(missing) == 0, missing


def main() -> int:
    lab = os.getenv("LAB")
    if not lab:
        print("LAB не задан. Например: LAB=1", file=sys.stderr)
        return 1

    lab_dir = ROOT / "labs" / f"lab-{lab}"
    if not lab_dir.exists():
        print(f"Папка лабораторной не найдена: {lab_dir}", file=sys.stderr)
        return 1

    lang, source = detect_language(lab_dir)
    build_dir = BUILD_ROOT / f"lab-{lab}"
    cmd = compile_program(lang, source, build_dir)

    manifest = read_manifest(lab)
    show_answers = bool(manifest.get("show_answers"))
    input_description = manifest.get("input_description")
    select_variant_by_output = bool(manifest.get("select_variant_by_output"))
    tests = manifest.get("tests", [])
    timeout_sec = int(manifest.get("timeout_sec", 5))
    default_tol = float(manifest.get("solution_tolerance", 1e-3))

    if input_description:
        print("Формат ввода:")
        print(input_description)
        print("")

    if not tests:
        print("Манифест не содержит тестов.", file=sys.stderr)
        return 1

    failed = 0
    for index, test in enumerate(tests, start=1):
        lab_tests_dir = TESTS_ROOT / f"lab-{lab}"
        input_dir = lab_tests_dir / "input"
        expected_dir = lab_tests_dir / "expected"
        input_data = resolve_input(test, input_dir)
        input_text = input_data.decode("utf-8", errors="replace")
        print(f"\nТест {index}:")
        print(input_text)
        variants = test.get("variants")
        expected = normalize_expected(test.get("out_contains"), expected_dir)
        expected_regex = normalize_expected(test.get("out_regex"), expected_dir)
        result = run_test(cmd, input_data, timeout_sec)
        stdout = result.stdout.decode("utf-8", errors="replace")
        stderr = result.stderr.decode("utf-8", errors="replace")
        output_text = f"{stdout}\n{stderr}" if stderr else stdout

        if variants:
            passed = False
            missing = []
            selected_variant = None
            selected_label = ""
            last_variant = None
            if select_variant_by_output:
                first_line = extract_first_line(output_text)
                normalized_first = normalize_text(first_line)
                for variant in variants:
                    selector = get_variant_selector(variant)
                    if selector and normalize_text(selector) in normalized_first:
                        selected_variant = variant
                        selected_label = variant.get("description") or selector
                        break

            variant_list = [selected_variant] if selected_variant else variants
            for variant in variant_list:
                last_variant = variant
                variant_expected = normalize_expected(variant.get("out_contains"), expected_dir)
                variant_regex = normalize_expected(variant.get("out_regex"), expected_dir)
                passed, missing = evaluate_variant(
                    output_text,
                    {
                        "out_contains": variant_expected,
                        "out_regex": variant_regex,
                        "expected_solution": variant.get("expected_solution"),
                        "solution_tolerance": variant.get("solution_tolerance"),
                        "use_input_tolerance": variant.get("use_input_tolerance"),
                        "tolerance_scale": variant.get("tolerance_scale"),
                    },
                    input_text,
                    default_tol,
                )
                if passed:
                    break
                if selected_variant:
                    break
        else:
            missing = []
            missing.extend(check_contains(output_text, expected))
            missing.extend(check_regex(output_text, expected_regex))
            if "expected_solution" in test:
                if test.get("use_input_tolerance"):
                    scale = float(test.get("tolerance_scale", 1.0))
                    tol = parse_input_tolerance(input_text, default_tol) * scale
                else:
                    tol = float(test.get("solution_tolerance", default_tol))
                missing.extend(check_solution(output_text, test.get("expected_solution", []), tol))
            passed = len(missing) == 0

        if not passed:
            failed += 1
            if output_text:
                print("\n--- OUTPUT (stdout+stderr) ---")
                print(output_text)
                print("--- END OUTPUT ---\n")
            if variants and select_variant_by_output and selected_label:
                print(f"Выбранный вариант: {selected_label}")
            if show_answers:
                if variants:
                    variant_for_expected = selected_variant or last_variant
                    exp_contains = normalize_expected(variant_for_expected.get("out_contains"), expected_dir)
                    exp_regex = normalize_expected(variant_for_expected.get("out_regex"), expected_dir)
                    exp_solution = variant_for_expected.get("expected_solution")
                else:
                    exp_contains = expected
                    exp_regex = expected_regex
                    exp_solution = test.get("expected_solution")
                details = format_expected(exp_contains, exp_regex, exp_solution)
                if details:
                    print(details)
            test_label = test.get("description") or f"#{index}"
            print(f"Тест {test_label} не прошел")
        else:
            test_label = test.get("description") or f"#{index}"
            print(f"Тест {test_label} прошел")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())


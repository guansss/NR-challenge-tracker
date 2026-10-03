"""Run offline Nightreign screen recognition against the supplied screenshots."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import cv2
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.nr_challenge_tracker.recognition import RecognitionEngine
from tools.project_config import load_config

CONFIG = load_config(ROOT)
PATHS = CONFIG["paths"]
RECOGNITION_CONFIG = CONFIG["recognition"]
MANIFEST_PATH = ROOT / PATHS["template_manifest"]
PREPARATION_DIR = ROOT / PATHS["preparation_screens"]
RESULT_DIRS = (
    ROOT / PATHS["result_screens"],
    ROOT / PATHS["abnormal_result_screens"],
)
PREPARATION_NIGHTLORD_ROI = tuple(RECOGNITION_CONFIG["preparation_nightlord_roi"])
RESULT_NIGHTLORD_SEARCH_ROI = (0.0, 0.50, 0.40, 0.48)
RESULT_PROGRESS_ROI = tuple(RECOGNITION_CONFIG["result_progress_roi"])
GRID_X = tuple(RECOGNITION_CONFIG["nightfarer_grid_x"])
GRID_Y = tuple(RECOGNITION_CONFIG["nightfarer_grid_y"])
SELECTION_MARKER_IN_TILE = tuple(RECOGNITION_CONFIG["selection_marker_in_tile"])
REFERENCE_WIDTH, REFERENCE_HEIGHT = RECOGNITION_CONFIG["source_dimensions"]
MIN_TEMPLATE_SCORE = 0.50
MIN_IDENTITY_MARGIN = 0.04
MIN_VARIANT_SCORE_MARGIN = 0.004
MIN_PROGRESS_MARGIN = 0.015
MIN_VICTORY_MARGIN = 0.015


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def read_image(path: Path) -> Any:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    require(image is not None, f"Could not decode image: {path.relative_to(ROOT)}")
    return image


def load_manifest() -> dict[str, Any]:
    require(MANIFEST_PATH.is_file(), f"Missing template manifest: {MANIFEST_PATH}")
    manifest = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    require(isinstance(manifest, dict), "Template manifest must be a YAML mapping")
    require(manifest.get("schema_version") == 1, "Unsupported template manifest schema")
    return manifest


def asset_path(relative_path: str) -> Path:
    path = (ROOT / relative_path).resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError as error:
        raise ValueError(f"Template path escapes repository: {relative_path}") from error
    require(path.is_file(), f"Missing template: {relative_path}")
    return path


def normalized_crop(
    image: Any, box: tuple[float, float, float, float]
) -> Any:
    height, width = image.shape[:2]
    x, y, crop_width, crop_height = box
    left = round(x * width)
    top = round(y * height)
    right = round((x + crop_width) * width)
    bottom = round((y + crop_height) * height)
    require(
        0 <= left < right <= width and 0 <= top < bottom <= height,
        f"ROI outside image: {box} in {width}x{height}",
    )
    return image[top:bottom, left:right]


def resize_like(image: Any, reference: Any) -> Any:
    if image.shape[:2] == reference.shape[:2]:
        return image
    interpolation = cv2.INTER_AREA if image.shape[1] > reference.shape[1] else cv2.INTER_CUBIC
    return cv2.resize(image, (reference.shape[1], reference.shape[0]), interpolation=interpolation)


def resize_template_for_frame(template: Any, image: Any, manifest: dict[str, Any]) -> Any:
    source_width, source_height = manifest["source_dimensions"]
    scale_x = image.shape[1] / source_width
    scale_y = image.shape[0] / source_height
    width = max(1, round(template.shape[1] * scale_x))
    height = max(1, round(template.shape[0] * scale_y))
    interpolation = cv2.INTER_AREA if scale_x < 1 or scale_y < 1 else cv2.INTER_CUBIC
    return cv2.resize(template, (width, height), interpolation=interpolation)


def normalized_match(image: Any, template: Any) -> float:
    image = resize_like(image, template)
    return float(cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)[0, 0])


def best_match(region: Any, template: Any) -> tuple[float, Any]:
    if region.shape[0] < template.shape[0] or region.shape[1] < template.shape[1]:
        return -1.0, region[:0, :0]
    scores = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, point = cv2.minMaxLoc(scores)
    x, y = point
    return float(score), region[y : y + template.shape[0], x : x + template.shape[1]]


def result_progress(
    image: Any, progress_templates: dict[str, Any]
) -> dict[str, Any]:
    crop = normalized_crop(image, RESULT_PROGRESS_ROI)
    first_template = next(iter(progress_templates.values()))
    crop = resize_like(crop, first_template)
    _, width = crop.shape[:2]

    day_scores: dict[str, float] = {}
    day_region = crop[:, : round(width * 0.62)]
    for day, template_ids in {
        "day_1": ("day_1",),
        "day_2": ("day_2",),
        "day_3": ("day_3", "day_3_victory"),
    }.items():
        day_scores[day] = max(
            normalized_match(
                day_region,
                progress_templates[template_id][:, : day_region.shape[1]],
            )
            for template_id in template_ids
        )

    ranked_days = sorted(day_scores.items(), key=lambda entry: entry[1], reverse=True)
    best_day, best_day_score = ranked_days[0]
    day_margin = best_day_score - ranked_days[1][1]
    day = (
        best_day
        if best_day_score >= MIN_TEMPLATE_SCORE and day_margin >= MIN_PROGRESS_MARGIN
        else "unknown"
    )

    victory_region = crop[:, round(width * 0.62) :]
    victory_scores = {
        "day_3": normalized_match(
            victory_region,
            progress_templates["day_3"][:, round(width * 0.62) :],
        ),
        "day_3_victory": normalized_match(
            victory_region,
            progress_templates["day_3_victory"][:, round(width * 0.62) :],
        ),
    }
    ranked_victory = sorted(
        victory_scores.items(), key=lambda entry: entry[1], reverse=True
    )
    best_victory, best_victory_score = ranked_victory[0]
    victory_margin = best_victory_score - ranked_victory[1][1]
    if best_victory_score < MIN_TEMPLATE_SCORE or victory_margin < MIN_VICTORY_MARGIN:
        victory: bool | None = None
    else:
        victory = best_victory == "day_3_victory"

    if day == "day_3" and victory is True:
        outcome = "day_3_victory"
    elif day == "day_3" and victory is False:
        outcome = "day_3"
    elif day in {"day_1", "day_2"} and victory is False:
        outcome = day
    else:
        outcome = "unknown"

    return {
        "day": day,
        "day_confidence": best_day_score,
        "day_margin": day_margin,
        "victory": victory,
        "victory_confidence": best_victory_score,
        "victory_margin": victory_margin,
        "outcome": outcome,
    }


def result_nightlord(
    image: Any, nightlords: list[dict[str, Any]], manifest: dict[str, Any]
) -> dict[str, Any]:
    region = normalized_crop(image, RESULT_NIGHTLORD_SEARCH_ROI)
    candidates: list[dict[str, Any]] = []
    for nightlord in nightlords:
        variants = nightlord.get("result_icon_templates", {})
        scores: list[tuple[str, float, Any, Any]] = []
        for variant in ("normal", "everdark"):
            path = variants.get(variant)
            if not path:
                continue
            template = resize_template_for_frame(
                read_image(asset_path(path)), image, manifest
            )
            score, _matched_crop = best_match(region, template)
            scores.append((variant, score, None, template))
        if scores:
            ranked_variants = sorted(
                scores, key=lambda entry: entry[1], reverse=True
            )
            variant, score, _, _ = ranked_variants[0]
            candidates.append(
                {
                    "id": nightlord["id"],
                    "variant": variant,
                    "score": score,
                    "variant_score_margin": (
                        score - ranked_variants[1][1]
                        if len(ranked_variants) > 1
                        else 1.0
                    ),
                }
            )

    candidates.sort(key=lambda entry: entry["score"], reverse=True)
    if not candidates:
        return {"nightlord": None, "variant": "unknown", "confidence": 0.0}

    best = candidates[0]
    margin = best["score"] - (candidates[1]["score"] if len(candidates) > 1 else 0.0)
    if best["score"] < MIN_TEMPLATE_SCORE or margin < MIN_IDENTITY_MARGIN:
        return {
            "nightlord": None,
            "variant": "unknown",
            "confidence": best["score"],
            "identity_margin": margin,
        }

    variant = best["variant"]
    variant_score_margin = best["variant_score_margin"]
    if variant_score_margin < MIN_VARIANT_SCORE_MARGIN:
        variant = "unknown"

    return {
        "nightlord": best["id"],
        "variant": variant,
        "confidence": best["score"],
        "identity_margin": margin,
        "variant_score_margin": variant_score_margin,
    }


def preparation(image: Any, manifest: dict[str, Any]) -> dict[str, Any]:
    target_crop = normalized_crop(image, PREPARATION_NIGHTLORD_ROI)
    nightlord_scores: list[tuple[str, float]] = []
    for nightlord in manifest["nightlords"]:
        path = nightlord["templates"].get("normal")
        if path:
            nightlord_scores.append(
                (nightlord["id"], normalized_match(target_crop, read_image(asset_path(path))))
            )

    nightlord_scores.sort(key=lambda entry: entry[1], reverse=True)
    hidden_template = read_image(asset_path(manifest["markers"]["hidden_nightlord"]))
    hidden_score = normalized_match(target_crop, hidden_template)
    top_id, top_score = nightlord_scores[0]
    second_score = nightlord_scores[1][1]
    hidden = hidden_score > top_score and hidden_score >= MIN_TEMPLATE_SCORE
    selected_nightlord = None
    if not hidden and top_score >= MIN_TEMPLATE_SCORE and top_score - second_score >= MIN_IDENTITY_MARGIN:
        selected_nightlord = top_id

    nightfarers = manifest["nightfarers"]
    marker_scores: list[tuple[str, float]] = []
    for index, nightfarer in enumerate(nightfarers):
        marker = resize_template_for_frame(
            read_image(
                asset_path(
                    manifest["markers"]["unselected_nightfarers"][nightfarer["id"]]
                )
            ),
            image,
            manifest,
        )
        marker_width, marker_height = marker.shape[1], marker.shape[0]
        column = index % 5
        row = index // 5
        tile_left = round(GRID_X[column] * image.shape[1] / REFERENCE_WIDTH)
        tile_top = round(GRID_Y[row] * image.shape[0] / REFERENCE_HEIGHT)
        marker_x, marker_y, _, _ = SELECTION_MARKER_IN_TILE
        left = tile_left + round(marker_x * image.shape[1] / REFERENCE_WIDTH)
        top = tile_top + round(marker_y * image.shape[0] / REFERENCE_HEIGHT)
        tile_region = image[top : top + marker_height, left : left + marker_width]
        marker_scores.append((nightfarer["id"], normalized_match(tile_region, marker)))

    marker_scores.sort(key=lambda entry: entry[1])
    selected_nightfarer, selection_score = marker_scores[0]
    selection_margin = marker_scores[1][1] - selection_score
    screen = (
        "preparation"
        if selected_nightfarer is not None
        and (hidden or selected_nightlord is not None)
        else "unknown"
    )
    return {
        "screen": screen,
        "nightlord": "hidden" if hidden else selected_nightlord,
        "nightlord_confidence": max(top_score, hidden_score),
        "nightfarer": selected_nightfarer,
        "nightfarer_confidence": (1.0 - selection_score) / 2.0,
        "nightfarer_margin": selection_margin,
    }


def recognize(image: Any, manifest: dict[str, Any]) -> dict[str, Any]:
    progress_templates = {
        name: read_image(asset_path(path))
        for name, path in manifest["progress_templates"].items()
    }
    progress = result_progress(image, progress_templates)
    if progress["day_confidence"] >= MIN_TEMPLATE_SCORE:
        result = result_nightlord(image, manifest["nightlords"], manifest)
        return {"screen": "result", **progress, **result}
    return preparation(image, manifest)


def expected_result(path: Path) -> dict[str, str]:
    nightlord_label, progress_label = path.stem.lower().split("_", 1)
    variant = "everdark" if nightlord_label.endswith("-everdark") else "normal"
    nightlord = nightlord_label.removesuffix("-everdark")
    outcomes = {
        "day1": "day_1",
        "day2": "day_2",
        "day3": "day_3",
        "victory": "day_3_victory",
    }
    require(progress_label in outcomes, f"Unknown result label in {path.name}")
    return {"nightlord": nightlord, "variant": variant, "outcome": outcomes[progress_label]}


def expected_preparation(path: Path) -> dict[str, str]:
    nightlord, nightfarer = path.stem.lower().split("_", 1)
    return {
        "nightlord": nightlord,
        "nightfarer": nightfarer,
    }


def result_screenshots() -> list[Path]:
    return [path for directory in RESULT_DIRS for path in sorted(directory.glob("*.jpg"))]


def run_dataset(
    manifest: dict[str, Any],
    resolution: tuple[int, int] | None,
    engine: RecognitionEngine,
) -> int:
    totals: dict[str, dict[str, list[int]]] = {}

    def record(group: str, field: str, actual: str, expected: str) -> None:
        group_totals = totals.setdefault(group, {})
        correct, count = group_totals.setdefault(field, [0, 0])
        group_totals[field] = [correct + (actual == expected), count + 1]

    all_correct = True
    for path in sorted(PREPARATION_DIR.glob("*.jpg")):
        expected = expected_preparation(path)
        image = read_image(path)
        if resolution is not None:
            image = cv2.resize(image, resolution, interpolation=cv2.INTER_AREA)
        result = engine.recognize(image)
        record("preparation", "screen", result["screen"], "preparation")
        for field, expected_value in expected.items():
            actual = result.get(field) or "unknown"
            record("preparation", field, actual, expected_value)
            all_correct = all_correct and actual == expected_value
        all_correct = all_correct and result["screen"] == "preparation"
        print(
            f"{path.relative_to(ROOT).as_posix()}: screen={result['screen']} "
            f"nightlord={result.get('nightlord')}/{expected['nightlord']} "
            f"nightfarer={result.get('nightfarer')}/{expected['nightfarer']}"
        )

    for path in result_screenshots():
        expected = expected_result(path)
        image = read_image(path)
        if resolution is not None:
            image = cv2.resize(image, resolution, interpolation=cv2.INTER_AREA)
        result = engine.recognize(image)
        record(path.parent.name, "screen", result["screen"], "result")
        all_correct = all_correct and result["screen"] == "result"
        values = []
        for field in ("nightlord", "variant", "outcome"):
            actual = result.get(field) or "unknown"
            group = path.parent.name
            record(group, field, actual, expected[field])
            all_correct = all_correct and actual == expected[field]
            values.append(f"{field}={actual}/{expected[field]}")
        print(
            f"{path.relative_to(ROOT).as_posix()}: screen={result['screen']} "
            f"nightlord_conf={result.get('confidence', 0.0):.3f} "
            f"day_conf={result.get('day_confidence', 0.0):.3f} "
            f"victory_conf={result.get('victory_confidence', 0.0):.3f} "
            + " ".join(values)
        )

    print("\nDataset recognition accuracy:")
    for group, fields in totals.items():
        print(f"  {group}:")
        for field, (correct, count) in fields.items():
            print(f"    {field}: {correct}/{count}")
    print(
        "  Note: normal result screenshots supply template references; "
        "abnormal results are held out."
    )
    if resolution is not None:
        print(f"  Frame size: {resolution[0]}x{resolution[1]}")
    return 0 if all_correct else 1


def parse_resolution(value: str) -> tuple[int, int]:
    try:
        width_text, height_text = value.lower().split("x", 1)
        width, height = int(width_text), int(height_text)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Resolution must be WIDTHxHEIGHT") from error
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("Resolution dimensions must be positive")
    return width, height


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        action="store_true",
        help="Run filename-labeled evaluation on both result screenshot folders.",
    )
    parser.add_argument(
        "--resolution",
        type=parse_resolution,
        help="Resize dataset screenshots before evaluation, for example 1920x1080.",
    )
    parser.add_argument("images", nargs="*", type=Path, help="Screenshots to recognize")
    args = parser.parse_args()

    try:
        manifest = load_manifest()
        engine = RecognitionEngine(ROOT, CONFIG, manifest)
        if args.dataset:
            return run_dataset(manifest, args.resolution, engine)
        if not args.images:
            parser.error("Provide screenshot paths or use --dataset")
        for path in args.images:
            image = read_image(path if path.is_absolute() else ROOT / path)
            print(f"{path}: {engine.recognize(image)}")
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as error:
        print(f"Recognition failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
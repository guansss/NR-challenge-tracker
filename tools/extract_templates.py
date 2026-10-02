"""Extract labeled Nightreign UI crops from the supplied screenshot dataset."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import cv2
import yaml

ROOT = Path(__file__).resolve().parents[1]
PREPARATION_DIR = ROOT / "assets" / "dataset" / "preparation-screens"
RESULT_DIR = ROOT / "assets" / "dataset" / "result-screens"
OUTPUT_DIR = ROOT / "assets" / "templates"
MANIFEST_PATH = OUTPUT_DIR / "manifest.yaml"
CONTACT_SHEET_PATH = OUTPUT_DIR / "contact_sheet.png"

NIGHTFARERS = (
    ("wylder", "Wylder"),
    ("guardian", "Guardian"),
    ("ironeye", "Ironeye"),
    ("duchess", "Duchess"),
    ("raider", "Raider"),
    ("revenant", "Revenant"),
    ("recluse", "Recluse"),
    ("executor", "Executor"),
    ("scholar", "Scholar"),
    ("undertaker", "Undertaker"),
)

NIGHTLORD_NAMES = {
    "adel": "Adel",
    "caligo": "Caligo",
    "fulghor": "Fulghor",
    "gladius": "Gladius",
    "gnoster": "Gnoster",
    "harmonia": "Harmonia",
    "heolstor": "Heolstor",
    "libra": "Libra",
    "maris": "Maris",
    "straghess": "Straghess",
}

# Normalized to the supplied 16:9 screenshots. The portrait grid uses its
# measured 2560x1440 cell positions, scaled to each source image's dimensions.
PREPARATION_NIGHTLORD_ROI = (0.051, 0.039, 0.042, 0.07)
RESULT_NIGHTLORD_ROI = (0.13, 0.77, 0.03, 0.055)
RESULT_PROGRESS_ROI = (0.692, 0.164, 0.263, 0.043)
GRID_X = (120, 259, 398, 536, 675)
GRID_Y = (389, 529)
GRID_WIDTH = 134
GRID_HEIGHT = 134
GRID_MARGIN = 25
SELECTION_MARKER_IN_TILE = (2, 2, 44, 44)
REFERENCE_WIDTH = 2560
REFERENCE_HEIGHT = 1440


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def read_image(path: Path) -> Any:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    require(image is not None, f"Could not decode image: {path.relative_to(ROOT)}")
    return image


def normalized_box_to_pixels(
    box: tuple[float, float, float, float], width: int, height: int
) -> tuple[int, int, int, int]:
    x, y, crop_width, crop_height = box
    left = round(x * width)
    top = round(y * height)
    right = round((x + crop_width) * width)
    bottom = round((y + crop_height) * height)
    return left, top, right, bottom


def pixel_box_to_normalized(
    box: tuple[int, int, int, int], width: int, height: int
) -> list[float]:
    left, top, right, bottom = box
    return [
        round(left / width, 6),
        round(top / height, 6),
        round((right - left) / width, 6),
        round((bottom - top) / height, 6),
    ]


def crop_image(image: Any, box: tuple[int, int, int, int], description: str) -> Any:
    height, width = image.shape[:2]
    left, top, right, bottom = box
    require(
        0 <= left < right <= width and 0 <= top < bottom <= height,
        f"Crop outside source image for {description}: {box} in {width}x{height}",
    )
    crop = image[top:bottom, left:right]
    require(crop.size > 0, f"Empty crop for {description}")
    return crop


def write_asset(
    image: Any,
    relative_path: str,
    source_path: Path,
    source_box: tuple[int, int, int, int],
    image_dimensions: tuple[int, int],
    label: str,
) -> dict[str, Any]:
    output_path = OUTPUT_DIR / relative_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    crop = crop_image(image, source_box, label)
    require(cv2.imwrite(str(output_path), crop), f"Could not write {output_path}")
    width, height = image_dimensions
    return {
        "id": label,
        "path": output_path.relative_to(ROOT).as_posix(),
        "source": source_path.relative_to(ROOT).as_posix(),
        "source_box_px": list(source_box),
        "source_box_normalized": pixel_box_to_normalized(source_box, width, height),
        "source_dimensions": [width, height],
        "template_dimensions": [int(crop.shape[1]), int(crop.shape[0])],
    }


def previous_asset_paths() -> set[Path]:
    if not MANIFEST_PATH.is_file():
        return set()
    previous_manifest = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    require(
        isinstance(previous_manifest, dict), "Existing manifest must be a YAML mapping"
    )
    previous_assets = previous_manifest.get("assets", [])
    require(
        isinstance(previous_assets, list), "Existing manifest asset list is invalid"
    )

    paths: set[Path] = set()
    for asset in previous_assets:
        relative_path = Path(asset["path"])
        require(
            not relative_path.is_absolute() and ".." not in relative_path.parts,
            f"Unsafe path in existing manifest: {relative_path}",
        )
        output_path = (ROOT / relative_path).resolve()
        try:
            output_path.relative_to(OUTPUT_DIR.resolve())
        except ValueError as error:
            raise ValueError(
                f"Path in existing manifest is outside the template directory: {relative_path}"
            ) from error
        paths.add(output_path)
    return paths


def preparation_files() -> dict[str, Path]:
    files: dict[str, Path] = {}
    for path in sorted(PREPARATION_DIR.glob("*.jpg")):
        parts = path.stem.lower().split("_")
        require(len(parts) == 2, f"Unexpected preparation filename: {path.name}")
        nightlord_id, nightfarer_id = parts
        require(
            nightfarer_id in {identifier for identifier, _ in NIGHTFARERS},
            f"Unknown Nightfarer in {path.name}",
        )
        if nightlord_id != "hidden":
            require(
                nightlord_id in NIGHTLORD_NAMES, f"Unknown Nightlord in {path.name}"
            )
        files[path.name] = path
    require(files, f"No preparation screenshots found in {PREPARATION_DIR}")
    return files


def result_files() -> list[tuple[Path, str, bool, str]]:
    parsed: list[tuple[Path, str, bool, str]] = []
    for path in sorted(RESULT_DIR.glob("*.jpg")):
        require("_" in path.stem, f"Unexpected result filename: {path.name}")
        nightlord_label, progress_label = path.stem.lower().split("_", 1)
        is_everdark = nightlord_label.endswith("-everdark")
        nightlord_id = nightlord_label.removesuffix("-everdark")
        require(nightlord_id in NIGHTLORD_NAMES, f"Unknown Nightlord in {path.name}")
        require(
            progress_label in {"day1", "day2", "day3", "victory"},
            f"Unknown progress label in {path.name}",
        )
        parsed.append((path, nightlord_id, is_everdark, progress_label))
    require(parsed, f"No result screenshots found in {RESULT_DIR}")
    return parsed


def validate_dataset(
    prep: dict[str, Path], results: list[tuple[Path, str, bool, str]]
) -> None:
    nightlords = {
        path.stem.lower().split("_", 1)[0]
        for path in prep.values()
        if not path.stem.lower().startswith("hidden_")
    }
    require(
        nightlords == set(NIGHTLORD_NAMES),
        f"Preparation Nightlord coverage mismatch: {sorted(nightlords)}",
    )
    require(
        any(path.stem.lower().startswith("hidden_") for path in prep.values()),
        "Missing hidden-Nightlord preparation screenshot",
    )
    selected_nightfarers = {
        path.stem.lower().split("_", 1)[1] for path in prep.values()
    }
    require(
        "executor" in selected_nightfarers,
        "Need an Executor preparation screenshot for the blue selection marker",
    )
    everdark_nightlords = {nightlord for _, nightlord, dark, _ in results if dark}
    require(
        len(everdark_nightlords) == 8,
        f"Expected 8 Everdark examples, found {len(everdark_nightlords)}",
    )
    progress_labels = {progress for _, _, _, progress in results}
    require(
        progress_labels == {"day1", "day2", "day3", "victory"},
        f"Unexpected result progress coverage: {sorted(progress_labels)}",
    )


def generate() -> dict[str, Any]:
    old_asset_paths = previous_asset_paths()
    prep = preparation_files()
    results = result_files()
    validate_dataset(prep, results)

    loaded: dict[Path, Any] = {}
    dimensions: set[tuple[int, int]] = set()
    for path in [*prep.values(), *(entry[0] for entry in results)]:
        if path not in loaded:
            loaded[path] = read_image(path)
            height, width = loaded[path].shape[:2]
            dimensions.add((width, height))
    require(len(dimensions) == 1, f"Source dimensions differ: {sorted(dimensions)}")
    width, height = next(iter(dimensions))
    require(
        abs(width / height - 16 / 9) < 0.002,
        f"Expected 16:9 source screenshots, found {width}x{height}",
    )

    assets: list[dict[str, Any]] = []
    nightlord_templates: dict[str, dict[str, str | None]] = {
        identifier: {"normal": None, "everdark": None} for identifier in NIGHTLORD_NAMES
    }
    result_icon_templates: dict[str, dict[str, str | None]] = {
        identifier: {"normal": None, "everdark": None} for identifier in NIGHTLORD_NAMES
    }
    for path in prep.values():
        nightlord_id = path.stem.lower().split("_", 1)[0]
        if nightlord_id == "hidden":
            continue
        image = loaded[path]
        box = normalized_box_to_pixels(PREPARATION_NIGHTLORD_ROI, width, height)
        asset = write_asset(
            image,
            f"nightlord_preparation_icons/{nightlord_id}.png",
            path,
            box,
            (width, height),
            f"nightlord:{nightlord_id}:normal",
        )
        assets.append(asset)
        nightlord_templates[nightlord_id]["normal"] = asset["path"]

    hidden_path = next(
        path for path in prep.values() if path.stem.lower().startswith("hidden_")
    )
    hidden_box = normalized_box_to_pixels(PREPARATION_NIGHTLORD_ROI, width, height)
    assets.append(
        write_asset(
            loaded[hidden_path],
            "markers/hidden_nightlord.png",
            hidden_path,
            hidden_box,
            (width, height),
            "marker:hidden_nightlord",
        )
    )

    # Avoid using the selected character's screenshot for its portrait so the
    # blue selection emblem cannot contaminate that identity template.
    character_sources: dict[str, Path] = {}
    for identifier, _ in NIGHTFARERS:
        candidates = [
            path
            for path in prep.values()
            if path.stem.lower().split("_", 1)[1] != identifier
        ]
        require(candidates, f"No unselected portrait source for {identifier}")
        character_sources[identifier] = candidates[0]

    for index, (identifier, _) in enumerate(NIGHTFARERS):
        column = index % 5
        row = index // 5
        left = round(GRID_X[column] * width / REFERENCE_WIDTH) + GRID_MARGIN
        top = round(GRID_Y[row] * height / REFERENCE_HEIGHT) + GRID_MARGIN
        cell_width = round(GRID_WIDTH * width / REFERENCE_WIDTH) - 2 * GRID_MARGIN
        cell_height = round(GRID_HEIGHT * height / REFERENCE_HEIGHT) - 2 * GRID_MARGIN
        box = (left, top, left + cell_width, top + cell_height)
        source = character_sources[identifier]
        assets.append(
            write_asset(
                loaded[source],
                f"nightfarers/{identifier}.png",
                source,
                box,
                (width, height),
                f"nightfarer:{identifier}",
            )
        )

    executor_path = next(
        path for path in prep.values() if path.stem.lower().endswith("_executor")
    )
    executor_index = next(
        index
        for index, (identifier, _) in enumerate(NIGHTFARERS)
        if identifier == "executor"
    )
    marker_column = executor_index % 5
    marker_row = executor_index // 5
    tile_left = round(GRID_X[marker_column] * width / REFERENCE_WIDTH)
    tile_top = round(GRID_Y[marker_row] * height / REFERENCE_HEIGHT)
    marker_x, marker_y, marker_width, marker_height = SELECTION_MARKER_IN_TILE
    selection_box = (
        tile_left + marker_x,
        tile_top + marker_y,
        tile_left + marker_x + marker_width,
        tile_top + marker_y + marker_height,
    )
    assets.append(
        write_asset(
            loaded[executor_path],
            "markers/selected_nightfarer.png",
            executor_path,
            selection_box,
            (width, height),
            "marker:selected_nightfarer",
        )
    )

    progress_values = {
        "day1": "day_1",
        "day2": "day_2",
        "day3": "day_3",
        "victory": "day_3_victory",
    }
    result_samples: list[dict[str, Any]] = []
    result_icon_assets: dict[tuple[str, str], dict[str, Any]] = {}
    progress_template_assets: dict[str, dict[str, Any]] = {}
    badge_box = normalized_box_to_pixels(RESULT_NIGHTLORD_ROI, width, height)
    progress_box = normalized_box_to_pixels(RESULT_PROGRESS_ROI, width, height)
    for path, nightlord_id, is_everdark, progress_label in results:
        image = loaded[path]
        variant = "everdark" if is_everdark else "normal"
        result_stem = path.stem.lower()
        icon_key = (nightlord_id, variant)
        icon_asset = result_icon_assets.get(icon_key)
        if icon_asset is None:
            icon_filename = (
                f"{nightlord_id}-everdark.png" if is_everdark else f"{nightlord_id}.png"
            )
            icon_asset = write_asset(
                image,
                f"nightlord_result_icons/{icon_filename}",
                path,
                badge_box,
                (width, height),
                f"result_nightlord:{nightlord_id}:{variant}",
            )
            result_icon_assets[icon_key] = icon_asset
            assets.append(icon_asset)
            result_icon_templates[nightlord_id][variant] = icon_asset["path"]
        if is_everdark:
            nightlord_templates[nightlord_id]["everdark"] = icon_asset["path"]

        progress_id = progress_values[progress_label]
        progress_asset = progress_template_assets.get(progress_id)
        if progress_asset is None:
            progress_asset = write_asset(
                image,
                f"result_progress/{progress_id}.png",
                path,
                progress_box,
                (width, height),
                f"result_progress:{progress_id}",
            )
            progress_template_assets[progress_id] = progress_asset
            assets.append(progress_asset)
        result_samples.append(
            {
                "source": path.relative_to(ROOT).as_posix(),
                "nightlord_id": nightlord_id,
                "variant": variant,
                "progress_label_from_filename": progress_id,
                "nightlord_icon_template": icon_asset["path"],
                "progress_crop": progress_asset["path"],
            }
        )

    nightfarer_catalog = [
        {
            "id": identifier,
            "display_name": display_name,
            "portrait_template": f"assets/templates/nightfarers/{identifier}.png",
        }
        for identifier, display_name in NIGHTFARERS
    ]
    nightlord_catalog = [
        {
            "id": identifier,
            "display_name": display_name,
            "everdark_available_in_dataset": any(
                sample[1] == identifier and sample[2] for sample in results
            ),
            "templates": nightlord_templates[identifier],
            "result_icon_templates": result_icon_templates[identifier],
        }
        for identifier, display_name in NIGHTLORD_NAMES.items()
    ]
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "source_dimensions": [width, height],
        "source_aspect_ratio": "16:9",
        "nightfarers": nightfarer_catalog,
        "nightlords": nightlord_catalog,
        "markers": {
            "hidden_nightlord": "assets/templates/markers/hidden_nightlord.png",
            "selected_nightfarer": "assets/templates/markers/selected_nightfarer.png",
        },
        "progress_templates": {
            progress_id: asset["path"]
            for progress_id, asset in progress_template_assets.items()
        },
        "result_progress_samples": result_samples,
        "notes": [
            "Source filenames provide labels; result samples are not a complete outcome matrix.",
            "Progress crops are labeled by filename. The crop alone is not asserted to distinguish Day 3 victory from Day 3 without victory.",
            "Crop coordinates describe source screenshots and are normalized in addition to pixel coordinates.",
            "Normal Nightlord identity references come from preparation screens; Everdark references come from labeled result screens.",
        ],
        "assets": assets,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    current_asset_paths = {(ROOT / asset["path"]).resolve() for asset in assets}
    for obsolete_path in old_asset_paths - current_asset_paths:
        if obsolete_path.is_file():
            obsolete_path.unlink()
    build_contact_sheet(assets)
    return manifest


def build_contact_sheet(assets: list[dict[str, Any]]) -> None:
    cell_width = 220
    image_height = 150
    label_height = 42
    columns = 5
    rows = (len(assets) + columns - 1) // columns
    sheet = cv2.UMat(
        rows * (image_height + label_height) + 24,
        columns * cell_width,
        cv2.CV_8UC3,
    ).get()
    sheet[:] = (30, 30, 30)

    for index, asset in enumerate(assets):
        image = read_image(ROOT / asset["path"])
        height, width = image.shape[:2]
        scale = min((cell_width - 12) / width, (image_height - 12) / height)
        resized = cv2.resize(
            image,
            (max(1, round(width * scale)), max(1, round(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
        column = index % columns
        row = index // columns
        x = column * cell_width + (cell_width - resized.shape[1]) // 2
        y = row * (image_height + label_height) + (image_height - resized.shape[0]) // 2
        sheet[y : y + resized.shape[0], x : x + resized.shape[1]] = resized
        label = Path(asset["path"]).stem[:30]
        cv2.putText(
            sheet,
            label[:34],
            (
                column * cell_width + 6,
                row * (image_height + label_height) + image_height + 18,
            ),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.38,
            (235, 235, 235),
            1,
            cv2.LINE_AA,
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    require(
        cv2.imwrite(str(CONTACT_SHEET_PATH), sheet), "Could not write contact sheet"
    )


def validate_output() -> dict[str, Any]:
    require(MANIFEST_PATH.is_file(), f"Missing manifest: {MANIFEST_PATH}")
    manifest = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    require(isinstance(manifest, dict), "Manifest must be a YAML mapping")
    require(manifest.get("schema_version") == 1, "Unsupported manifest schema")
    assets = manifest.get("assets")
    require(isinstance(assets, list) and assets, "Manifest has no asset list")

    for asset in assets:
        output_path = ROOT / asset["path"]
        require(output_path.is_file(), f"Missing generated template: {asset['path']}")
        image = read_image(output_path)
        expected = asset["template_dimensions"]
        require(
            [int(image.shape[1]), int(image.shape[0])] == expected,
            f"Template dimensions mismatch: {asset['path']}",
        )

    require(len(manifest.get("nightfarers", [])) == 10, "Expected 10 Nightfarers")
    require(len(manifest.get("nightlords", [])) == 10, "Expected 10 Nightlords")
    require(
        sum(
            1
            for nightlord in manifest["nightlords"]
            if nightlord["everdark_available_in_dataset"]
        )
        == 8,
        "Expected 8 Nightlords with Everdark dataset examples",
    )
    require(
        len(manifest.get("result_progress_samples", [])) == 18,
        "Expected 18 result samples",
    )
    icon_paths_by_key: dict[tuple[str, str], str] = {}
    for sample in manifest["result_progress_samples"]:
        key = (sample["nightlord_id"], sample["variant"])
        icon_path = sample["nightlord_icon_template"]
        require(
            key not in icon_paths_by_key or icon_paths_by_key[key] == icon_path,
            f"Inconsistent result icon template for {key}",
        )
        icon_paths_by_key[key] = icon_path
    icon_assets = {
        asset["path"]
        for asset in assets
        if asset["path"].startswith("assets/templates/nightlord_result_icons/")
    }
    require(
        set(icon_paths_by_key.values()) == icon_assets,
        "Expected one result icon template per Nightlord/variant key",
    )
    progress_paths_by_label: dict[str, str] = {}
    for sample in manifest["result_progress_samples"]:
        label = sample["progress_label_from_filename"]
        progress_path = sample["progress_crop"]
        require(
            label not in progress_paths_by_label
            or progress_paths_by_label[label] == progress_path,
            f"Inconsistent progress template for {label}",
        )
        progress_paths_by_label[label] = progress_path
    progress_assets = {
        asset["path"]
        for asset in assets
        if asset["path"].startswith("assets/templates/result_progress/")
    }
    require(
        set(progress_paths_by_label.values()) == progress_assets,
        "Expected one progress template per progress label",
    )
    require(
        manifest.get("progress_templates") == progress_paths_by_label,
        "Progress template catalog must match result samples",
    )
    require(CONTACT_SHEET_PATH.is_file(), "Missing contact sheet")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate existing generated assets without rewriting them.",
    )
    args = parser.parse_args()

    try:
        manifest = validate_output() if args.check else generate()
        if not args.check:
            validate_output()
        print(
            f"Validated {len(manifest['assets'])} crops from "
            f"{len(manifest['result_progress_samples'])} result screenshots."
        )
        print(f"Manifest: {MANIFEST_PATH.relative_to(ROOT)}")
        print(f"Contact sheet: {CONTACT_SHEET_PATH.relative_to(ROOT)}")
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as error:
        print(f"Template extraction failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

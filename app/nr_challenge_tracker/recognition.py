"""Cached OpenCV recognition engine for preparation and result screens."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import yaml


class RecognitionEngine:
    def __init__(
        self,
        root: Path,
        config: dict[str, Any],
        manifest: dict[str, Any] | None = None,
    ) -> None:
        self.root = root.resolve()
        self.config = config
        paths = config["paths"]
        self.manifest = manifest or self._load_manifest(
            self.root / paths["template_manifest"]
        )
        recognition = config["recognition"]
        self.preparation_roi = tuple(recognition["preparation_nightlord_roi"])
        self.progress_roi = tuple(recognition["result_progress_roi"])
        self.grid_x = tuple(recognition["nightfarer_grid_x"])
        self.grid_y = tuple(recognition["nightfarer_grid_y"])
        self.selection_marker_box = tuple(recognition["selection_marker_in_tile"])
        self.reference_width, self.reference_height = recognition["source_dimensions"]
        self.result_search_roi = tuple(
            recognition.get("result_nightlord_search_roi", [0.0, 0.50, 0.40, 0.48])
        )

        thresholds = recognition.get("thresholds", {})
        self.min_template_score = thresholds.get("template_score", 0.50)
        self.min_result_template_score = thresholds.get(
            "result_template_score", 0.56
        )
        self.min_identity_margin = thresholds.get("identity_margin", 0.04)
        self.min_variant_score_margin = thresholds.get("variant_score_margin", 0.004)
        self.min_progress_margin = thresholds.get("progress_margin", 0.015)
        self.min_victory_margin = thresholds.get("victory_margin", 0.015)

        source_dimensions = self.manifest["source_dimensions"]
        self.source_width, self.source_height = source_dimensions
        self.templates: dict[str, Any] = {}
        self._scaled_templates: dict[tuple[str, int, int], Any] = {}
        self._load_templates()

    @staticmethod
    def _load_manifest(path: Path) -> dict[str, Any]:
        manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
            raise ValueError("Invalid or unsupported template manifest")
        return manifest

    def _asset(self, relative_path: str) -> Any:
        path = (self.root / relative_path).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as error:
            raise ValueError(f"Template path escapes repository: {relative_path}") from error
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f"Could not decode template: {relative_path}")
        return image

    def _load_templates(self) -> None:
        self.templates["marker:hidden"] = self._asset(
            self.manifest["markers"]["hidden_nightlord"]
        )
        self.templates["marker:selected"] = self._asset(
            self.manifest["markers"]["selected_nightfarer"]
        )
        self.unselected_marker_templates = {
            nightfarer_id: self._asset(path)
            for nightfarer_id, path in self.manifest["markers"][
                "unselected_nightfarers"
            ].items()
        }
        self.preparation_templates: list[tuple[str, Any]] = []
        self.result_templates: dict[str, dict[str, Any]] = {}

        for nightlord in self.manifest["nightlords"]:
            nightlord_id = nightlord["id"]
            prep_path = nightlord.get("templates", {}).get("normal")
            if prep_path:
                key = f"prep:{nightlord_id}"
                self.templates[key] = self._asset(prep_path)
                self.preparation_templates.append((nightlord_id, self.templates[key]))

            result_templates: dict[str, Any] = {}
            for variant, path in nightlord.get("result_icon_templates", {}).items():
                if path:
                    key = f"result:{nightlord_id}:{variant}"
                    self.templates[key] = self._asset(path)
                    result_templates[variant] = self.templates[key]
            self.result_templates[nightlord_id] = result_templates

        self.progress_templates = {
            name: self._asset(path)
            for name, path in self.manifest["progress_templates"].items()
        }
        self.nightfarer_templates = [
            (nightfarer["id"], self._asset(nightfarer["portrait_template"]))
            for nightfarer in self.manifest["nightfarers"]
        ]

    @staticmethod
    def _normalized_crop(
        image: Any, box: tuple[float, float, float, float]
    ) -> Any:
        height, width = image.shape[:2]
        x, y, crop_width, crop_height = box
        left = round(x * width)
        top = round(y * height)
        right = round((x + crop_width) * width)
        bottom = round((y + crop_height) * height)
        if not (0 <= left < right <= width and 0 <= top < bottom <= height):
            raise ValueError(f"ROI outside image: {box} in {width}x{height}")
        return image[top:bottom, left:right]

    @staticmethod
    def _resize_like(image: Any, reference: Any) -> Any:
        if image.shape[:2] == reference.shape[:2]:
            return image
        interpolation = (
            cv2.INTER_AREA
            if image.shape[1] > reference.shape[1]
            else cv2.INTER_CUBIC
        )
        return cv2.resize(image, (reference.shape[1], reference.shape[0]), interpolation)

    def _template_for_frame(self, key: str, image: Any, template: Any) -> Any:
        height, width = image.shape[:2]
        cache_key = (key, width, height)
        cached = self._scaled_templates.get(cache_key)
        if cached is not None:
            return cached
        scale_x = width / self.source_width
        scale_y = height / self.source_height
        target_width = max(1, round(template.shape[1] * scale_x))
        target_height = max(1, round(template.shape[0] * scale_y))
        interpolation = (
            cv2.INTER_AREA if scale_x < 1 or scale_y < 1 else cv2.INTER_CUBIC
        )
        scaled = cv2.resize(template, (target_width, target_height), interpolation)
        self._scaled_templates[cache_key] = scaled
        return scaled

    @classmethod
    def _normalized_match(cls, image: Any, template: Any) -> float:
        image = cls._resize_like(image, template)
        return float(cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)[0, 0])

    @staticmethod
    def _best_match(
        region: Any, template: Any
    ) -> tuple[float, Any, tuple[int, int] | None]:
        if region.shape[0] < template.shape[0] or region.shape[1] < template.shape[1]:
            return -1.0, region[:0, :0], None
        scores = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
        _, score, _, point = cv2.minMaxLoc(scores)
        x, y = point
        return (
            float(score),
            region[y : y + template.shape[0], x : x + template.shape[1]],
            point,
        )

    def _result_progress(self, image: Any) -> dict[str, Any]:
        crop = self._normalized_crop(image, self.progress_roi)
        first_template = next(iter(self.progress_templates.values()))
        crop = self._resize_like(crop, first_template)
        _, width = crop.shape[:2]

        day_region = crop[:, : round(width * 0.62)]
        day_scores = {
            "day_1": self._normalized_match(
                day_region, self.progress_templates["day_1"][:, : day_region.shape[1]]
            ),
            "day_2": self._normalized_match(
                day_region, self.progress_templates["day_2"][:, : day_region.shape[1]]
            ),
            "day_3": max(
                self._normalized_match(
                    day_region,
                    self.progress_templates[name][:, : day_region.shape[1]],
                )
                for name in ("day_3", "day_3_victory")
            ),
        }
        ranked_days = sorted(day_scores.items(), key=lambda entry: entry[1], reverse=True)
        best_day, best_day_score = ranked_days[0]
        day_margin = best_day_score - ranked_days[1][1]
        day = (
            best_day
            if best_day_score >= self.min_template_score
            and day_margin >= self.min_progress_margin
            else "unknown"
        )

        victory: bool | None = None
        victory_confidence: float | None = None
        victory_margin: float | None = None
        if day == "day_3":
            victory_region = crop[:, round(width * 0.62) :]
            victory_scores = {
                name: self._normalized_match(
                    victory_region,
                    self.progress_templates[name][:, round(width * 0.62) :],
                )
                for name in ("day_3", "day_3_victory")
            }
            ranked_victory = sorted(
                victory_scores.items(), key=lambda entry: entry[1], reverse=True
            )
            best_victory, victory_confidence = ranked_victory[0]
            victory_margin = victory_confidence - ranked_victory[1][1]
            if (
                victory_confidence < self.min_template_score
                or victory_margin < self.min_victory_margin
            ):
                victory = None
            else:
                victory = best_victory == "day_3_victory"

        if day == "day_3" and victory is True:
            outcome = "day_3_victory"
        elif day == "day_3" and victory is False:
            outcome = "day_3"
        elif day in {"day_1", "day_2"}:
            outcome = day
        else:
            outcome = "unknown"
        return {
            "day": day,
            "day_confidence": best_day_score,
            "day_margin": day_margin,
            "victory": victory,
            "victory_confidence": victory_confidence,
            "victory_margin": victory_margin,
            "outcome": outcome,
        }

    def _result_nightlord(self, image: Any) -> dict[str, Any]:
        region = self._normalized_crop(image, self.result_search_roi)
        candidates: list[dict[str, Any]] = []
        for nightlord_id, variants in self.result_templates.items():
            scores: list[tuple[str, float, Any, Any, tuple[int, int] | None]] = []
            for variant, template in variants.items():
                key = f"result:{nightlord_id}:{variant}"
                scaled = self._template_for_frame(key, image, template)
                score, crop, point = self._best_match(region, scaled)
                scores.append((variant, score, crop, scaled, point))
            if scores:
                ranked_variants = sorted(
                    scores, key=lambda entry: entry[1], reverse=True
                )
                variant, score, _, scaled, point = ranked_variants[0]
                candidates.append(
                    {
                        "id": nightlord_id,
                        "variant": variant,
                        "score": score,
                        "match_point": point,
                        "match_size": (scaled.shape[1], scaled.shape[0]),
                        "variant_score_margin": (
                            score - ranked_variants[1][1]
                            if len(ranked_variants) > 1
                            else 1.0
                        ),
                    }
                )

        candidates.sort(key=lambda entry: entry["score"], reverse=True)
        if not candidates:
            return {
                "nightlord": None,
                "variant": "unknown",
                "confidence": 0.0,
                "nightlord_region": None,
            }
        best = candidates[0]
        margin = best["score"] - (
            candidates[1]["score"] if len(candidates) > 1 else 0.0
        )
        if (
            best["score"] < self.min_result_template_score
            or margin < self.min_identity_margin
        ):
            return {
                "nightlord": None,
                "variant": "unknown",
                "confidence": best["score"],
                "identity_margin": margin,
                "nightlord_region": None,
            }

        variant = best["variant"]
        variant_score_margin = best["variant_score_margin"]
        if variant_score_margin < self.min_variant_score_margin:
            variant = "unknown"
        match_point = best["match_point"]
        if match_point is None:
            return {
                "nightlord": None,
                "variant": "unknown",
                "confidence": best["score"],
                "identity_margin": margin,
                "nightlord_region": None,
            }
        search_left, search_top, _, _ = self._roi_pixels(
            self.result_search_roi, image.shape[1], image.shape[0]
        )
        match_x, match_y = match_point
        match_width, match_height = best["match_size"]
        return {
            "nightlord": best["id"],
            "variant": variant,
            "confidence": best["score"],
            "identity_margin": margin,
            "variant_score_margin": variant_score_margin,
            "nightlord_region": (
                search_left + match_x,
                search_top + match_y,
                search_left + match_x + match_width,
                search_top + match_y + match_height,
            ),
        }

    def _preparation(self, image: Any) -> dict[str, Any]:
        target_crop = self._normalized_crop(image, self.preparation_roi)
        nightlord_scores = [
            (nightlord_id, self._normalized_match(target_crop, template))
            for nightlord_id, template in self.preparation_templates
        ]
        nightlord_scores.sort(key=lambda entry: entry[1], reverse=True)
        hidden_score = self._normalized_match(
            target_crop, self.templates["marker:hidden"]
        )
        top_id, top_score = nightlord_scores[0]
        second_score = nightlord_scores[1][1]
        hidden = hidden_score > top_score and hidden_score >= self.min_template_score
        selected_nightlord = None
        if (
            not hidden
            and top_score >= self.min_template_score
            and top_score - second_score >= self.min_identity_margin
        ):
            selected_nightlord = top_id

        marker_scores: list[tuple[str, float]] = []
        for index, (nightfarer_id, _) in enumerate(self.nightfarer_templates):
            marker = self._template_for_frame(
                f"marker:unselected:{nightfarer_id}",
                image,
                self.unselected_marker_templates[nightfarer_id],
            )
            marker_width, marker_height = marker.shape[1], marker.shape[0]
            column = index % 5
            row = index // 5
            tile_left = round(self.grid_x[column] * image.shape[1] / self.reference_width)
            tile_top = round(self.grid_y[row] * image.shape[0] / self.reference_height)
            marker_x, marker_y, _, _ = self.selection_marker_box
            left = tile_left + round(marker_x * image.shape[1] / self.reference_width)
            top = tile_top + round(marker_y * image.shape[0] / self.reference_height)
            tile_region = image[top : top + marker_height, left : left + marker_width]
            marker_scores.append(
                (nightfarer_id, self._normalized_match(tile_region, marker))
            )

        marker_scores.sort(key=lambda entry: entry[1], reverse=True)
        selected, selection_score = marker_scores[-1]
        selection_margin = marker_scores[-2][1] - selection_score
        nightfarer = selected
        screen = (
            "preparation"
            if nightfarer is not None and (hidden or selected_nightlord is not None)
            else "unknown"
        )
        return {
            "screen": screen,
            "nightlord": "hidden" if hidden else selected_nightlord,
            "nightlord_confidence": max(top_score, hidden_score),
            "nightfarer": nightfarer,
            "nightfarer_confidence": (1.0 - selection_score) / 2.0,
            "nightfarer_margin": selection_margin,
        }

    def recognize(self, image: Any) -> dict[str, Any]:
        progress = self._result_progress(image)
        if progress["day"] != "unknown":
            result = self._result_nightlord(image)
            return {"screen": "result", **progress, **result}
        return self._preparation(image)

    @staticmethod
    def _roi_pixels(
        box: tuple[float, float, float, float], width: int, height: int
    ) -> tuple[int, int, int, int]:
        x, y, box_width, box_height = box
        return (
            round(x * width),
            round(y * height),
            round((x + box_width) * width),
            round((y + box_height) * height),
        )

    @staticmethod
    def _draw_debug_roi(
        image: Any,
        box: tuple[int, int, int, int],
        color: tuple[int, int, int],
    ) -> None:
        left, top, right, bottom = box
        cv2.rectangle(
            image,
            (left, top),
            (right - 1, bottom - 1),
            color,
            max(2, round(min(image.shape[1], image.shape[0]) / 500)),
        )

    def render_debug_image(self, image: Any, result: dict[str, Any]) -> Any:
        """Return a frame copy with the recognized screen's input ROIs outlined."""
        annotated = image.copy()
        height, width = annotated.shape[:2]
        screen = result.get("screen")

        if screen == "preparation":
            self._draw_debug_roi(
                annotated,
                self._roi_pixels(self.preparation_roi, width, height),
                (70, 220, 70),
            )
            nightfarer_id = result.get("nightfarer")
            marker_index = next(
                (
                    index
                    for index, (identifier, _) in enumerate(self.nightfarer_templates)
                    if identifier == nightfarer_id
                ),
                None,
            )
            if marker_index is not None:
                marker = self._template_for_frame(
                    "marker:selected", annotated, self.templates["marker:selected"]
                )
                column = marker_index % 5
                row = marker_index // 5
                tile_left = round(
                    self.grid_x[column] * width / self.reference_width
                )
                tile_top = round(self.grid_y[row] * height / self.reference_height)
                marker_x, marker_y, _, _ = self.selection_marker_box
                left = tile_left + round(marker_x * width / self.reference_width)
                top = tile_top + round(marker_y * height / self.reference_height)
                self._draw_debug_roi(
                    annotated,
                    (left, top, left + marker.shape[1], top + marker.shape[0]),
                    (220, 180, 30),
                )
        elif screen == "result":
            self._draw_debug_roi(
                annotated,
                self._roi_pixels(self.progress_roi, width, height),
                (0, 210, 255),
            )
            self._draw_debug_roi(
                annotated,
                self._roi_pixels(self.result_search_roi, width, height),
                (220, 50, 220),
            )
            nightlord_region = result.get("nightlord_region")
            if nightlord_region is not None:
                self._draw_debug_roi(
                    annotated,
                    nightlord_region,
                    (50, 255, 50),
                )

        return annotated
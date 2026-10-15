from __future__ import annotations

import csv
import json
import math
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import librosa
import numpy as np
from music21 import chord, converter, key, meter, note, stream


TAKING_FORM_LABELS = {
    "Exposition": "呈示部",
    "Development": "展开部",
    "Recapitulation": "再现部",
    "Coda": "尾声",
    "Introduction": "引子",
    "Main Theme": "主部",
    "Contrasting Middle": "中部",
}


@dataclass
class MeasureFeature:
    number: int
    offset: float
    duration: float
    vector: np.ndarray
    key_name: str
    cadence: str


def _safe_number(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _pitch_histogram(measure: stream.Measure) -> np.ndarray:
    hist = np.zeros(12, dtype=float)
    registers: list[float] = []
    onsets = 0
    for element in measure.recurse().notes:
        pitches = element.pitches if isinstance(element, chord.Chord) else [element.pitch]
        duration = max(float(element.quarterLength), 0.125)
        onsets += 1
        for pitch in pitches:
            hist[pitch.pitchClass] += duration
            registers.append(float(pitch.midi))
    total = hist.sum()
    if total:
        hist /= total
    register = (np.mean(registers) / 127.0) if registers else 0.0
    spread = (np.std(registers) / 48.0) if registers else 0.0
    density = min(1.0, onsets / max(float(measure.barDuration.quarterLength or 4), 1.0) / 8.0)
    return np.concatenate([hist, [register, spread, density]])


def _measure_key(measure: stream.Measure, global_key: key.Key) -> str:
    try:
        if len(measure.recurse().notes) >= 3:
            detected = measure.analyze("key")
            return detected.tonic.name + ("小调" if detected.mode == "minor" else "大调")
    except Exception:
        pass
    return global_key.tonic.name + ("小调" if global_key.mode == "minor" else "大调")


def _cadence_hint(measure: stream.Measure, global_key: key.Key) -> str:
    chords = list(measure.chordify().recurse().getElementsByClass(chord.Chord))
    if not chords:
        return "无明确终止"
    last = chords[-1]
    root = last.root()
    if root is None:
        return "需复核"
    tonic_pc = global_key.tonic.pitchClass
    dominant_pc = (tonic_pc + 7) % 12
    if root.pitchClass == tonic_pc:
        return "主和弦收束候选"
    if root.pitchClass == dominant_pc:
        return "属功能开放候选"
    return "非主属终止"


def extract_measure_features(score: stream.Score) -> tuple[list[MeasureFeature], key.Key]:
    try:
        global_key = score.analyze("key")
    except Exception:
        global_key = key.Key("C")
    chordified = score.chordify()
    measures = list(chordified.recurse().getElementsByClass(stream.Measure))
    if not measures:
        raise ValueError("MusicXML 中没有可分析的小节")
    features: list[MeasureFeature] = []
    for index, measure in enumerate(measures):
        number = _safe_number(measure.number, index + 1)
        duration = float(measure.barDuration.quarterLength or measure.duration.quarterLength or 4)
        features.append(
            MeasureFeature(
                number=number,
                offset=float(measure.offset),
                duration=duration,
                vector=_pitch_histogram(measure),
                key_name=_measure_key(measure, global_key),
                cadence=_cadence_hint(measure, global_key),
            )
        )
    return features, global_key


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denom) if denom else 0.0


def _choose_boundaries(matrix: np.ndarray) -> np.ndarray:
    count = matrix.shape[1]
    if count < 6:
        return np.array([0, count], dtype=int)
    candidates = range(3, min(7, max(4, count // 4 + 1)))
    best_score = -1e9
    best = np.array([0, count], dtype=int)
    recurrence = librosa.segment.recurrence_matrix(
        matrix, metric="cosine", mode="affinity", sym=True, full=True
    )
    for segments in candidates:
        if segments >= count:
            continue
        bounds = np.unique(
            np.concatenate([[0], librosa.segment.agglomerative(matrix, segments), [count]])
        ).astype(int)
        if len(bounds) < 3:
            continue
        within: list[float] = []
        between: list[float] = []
        for i in range(len(bounds) - 1):
            a, b = bounds[i], bounds[i + 1]
            block = recurrence[a:b, a:b]
            if block.size:
                within.append(float(np.mean(block)))
            if i + 2 < len(bounds):
                c = bounds[i + 2]
                cross = recurrence[a:b, b:c]
                if cross.size:
                    between.append(float(np.mean(cross)))
        lengths = np.diff(bounds)
        balance = float(np.min(lengths) / max(np.max(lengths), 1))
        score = (np.mean(within) if within else 0) - (np.mean(between) if between else 0) + 0.15 * balance
        if score > best_score:
            best_score, best = score, bounds
    return best


def _taking_form_annotations(path: Path) -> list[dict[str, str]]:
    root = Path(os.environ.get("TAKING_FORM_ROOT", Path(__file__).parent / "vendor" / "Taking-Form"))
    script = root / "markup" / "xml2table.py"
    if not script.exists():
        return []
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "taking-form.csv"
        try:
            subprocess.run(
                [shutil.which("python3") or "python3", str(script), str(path), str(output)],
                check=True,
                timeout=60,
                capture_output=True,
                text=True,
            )
            if not output.exists():
                return []
            with output.open(encoding="utf-8-sig", errors="replace") as handle:
                rows = list(csv.reader(handle))
            return [
                {"measure": row[0], "beat": row[1], "form": " / ".join(x for x in row[2:] if x)}
                for row in rows
                if len(row) >= 3 and row[0].strip()
            ]
        except Exception:
            return []


def _segment_labels(
    features: list[MeasureFeature], boundaries: np.ndarray, global_key: key.Key
) -> tuple[list[str], str, float, list[str]]:
    ranges = list(zip(boundaries[:-1], boundaries[1:]))
    vectors = [np.mean([f.vector for f in features[a:b]], axis=0) for a, b in ranges]
    first_last = _cosine(vectors[0], vectors[-1]) if len(vectors) >= 3 else 0.0
    tonic_name = global_key.tonic.name
    final_tonic = tonic_name in features[-1].key_name or "主和弦" in features[-1].cadence
    evidence = [f"首尾材料相似度 {first_last:.2f}", f"全曲中心调性 {tonic_name} {global_key.mode}"]
    if len(ranges) >= 3 and first_last >= 0.68:
        labels = ["主部"] + ["中部"] * (len(ranges) - 2) + ["再现部"]
        # Pitch-class return alone is not enough to assert a classical formal
        # function, so keep the score below the level of a definitive verdict.
        confidence = min(0.82, 0.48 + first_last * 0.26 + (0.04 if final_tonic else 0))
        form = "再现性三部结构候选"
        evidence.append("开头材料在末段回归，符合 Taking Form 的顶层再现关系")
        if len(ranges) == 3:
            evidence.append("若中段具有转调、主题碎片化且末段回归主调，可进一步解释为呈示部—展开部—再现部")
        return labels, form, confidence, evidence
    if len(ranges) >= 5:
        sims = [_cosine(vectors[0], v) for v in vectors]
        returns = sum(value >= 0.72 for value in sims[1:])
        if returns >= 2:
            labels = ["A" if value >= 0.72 else chr(ord("B") + i) for i, value in enumerate(sims)]
            evidence.append(f"主材料出现 {returns + 1} 次")
            return labels, "回旋性结构候选", min(0.9, 0.58 + returns * 0.08), evidence
    labels = [chr(ord("A") + i) for i in range(len(ranges))]
    evidence.append("未达到自动命名主部/再现部的相似度阈值，保留中性字母标签")
    return labels, "多段结构候选", 0.5, evidence


def _run_msaf_symbolic(matrix: np.ndarray) -> dict[str, Any]:
    """Run MSAF spectral clustering on measure-synchronous symbolic features.

    MSAF normally extracts PCP/MFCC from audio.  Because this workflow accepts a
    score, the pitch-class histogram is used as PCP and the register/density
    channels act as a timbral/local-motion proxy.  This keeps MSAF as a second
    opinion without asking the student to upload an audio rendering.
    """
    count = matrix.shape[1]
    if count < 10:
        return {"status": "skipped", "reason": "少于 10 小节，不适合 MSAF 谱聚类复核"}
    try:
        os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "music-form-mpl"))
        import msaf  # type: ignore
        from msaf.algorithms.scluster import main2  # type: ignore
    except Exception as exc:
        return {"status": "skipped", "reason": f"MSAF 不可用：{exc}"}
    try:
        width = min(9, max(2, count // 6))
        config = {
            "hier": False,
            "num_layers": min(10, count - 1),
            "scluster_k": min(4, max(2, count // 10)),
            "evec_smooth": min(9, max(3, count // 5)),
            "rec_smooth": min(9, max(3, count // 5)),
            "rec_width": width,
        }
        pcp = matrix[:12]
        local = matrix[12:]
        boundaries, labels, _ = main2.do_segmentation(pcp, local, config)
        return {
            "status": "ok",
            "mode": "measure-synchronous symbolic proxy",
            "boundaries_measures": [int(x) + 1 for x in boundaries],
            "labels": [int(x) for x in labels],
        }
    except Exception as exc:
        return {"status": "skipped", "reason": f"MSAF 谱聚类未完成：{exc}"}


def analyze_musicxml(path: Path) -> dict[str, Any]:
    score = converter.parse(str(path))
    features, global_key = extract_measure_features(score)
    matrix = np.stack([feature.vector for feature in features], axis=1)
    boundaries = _choose_boundaries(matrix)
    labels, form, confidence, evidence = _segment_labels(features, boundaries, global_key)
    sections = []
    for index, (start, end) in enumerate(zip(boundaries[:-1], boundaries[1:])):
        subset = features[start:end]
        sections.append(
            {
                "index": index + 1,
                "label": labels[index],
                "start_measure": subset[0].number,
                "end_measure": subset[-1].number,
                "key_start": subset[0].key_name,
                "key_end": subset[-1].key_name,
                "cadence": subset[-1].cadence,
                "evidence": f"m.{subset[0].number}–{subset[-1].number}；{subset[0].key_name} → {subset[-1].key_name}；{subset[-1].cadence}",
            }
        )
    taking_form = _taking_form_annotations(path)
    return {
        "source": "musicxml",
        "measure_count": len(features),
        "global_key": global_key.tonic.name + ("小调" if global_key.mode == "minor" else "大调"),
        "form": form,
        "confidence": round(confidence, 3),
        "sections": sections,
        "evidence": evidence,
        "engines": {
            "librosa_segment": "ok",
            "taking_form": "embedded annotations" if taking_form else "taxonomy/rules",
            "msaf": _run_msaf_symbolic(matrix),
        },
        "taking_form_annotations": taking_form[:100],
        "warning": "自动结果是可复核的分析假设。古典曲式命名必须同时核对主题、调性布局与终止式。",
    }


def image_to_musicxml(image_path: Path, output_dir: Path) -> Path:
    bundled = Path(__file__).parent / "audiveris-cli.sh"
    command = os.environ.get("AUDIVERIS_CMD") or shutil.which("audiveris")
    if not command and bundled.exists():
        command = str(bundled)
    if not command:
        raise RuntimeError("服务器未安装 Audiveris；图片分析需要先配置 AUDIVERIS_CMD")
    subprocess.run(
        [command, "-batch", "-transcribe", "-export", "-output", str(output_dir), "--", str(image_path)],
        check=True,
        timeout=600,
        capture_output=True,
        text=True,
    )
    candidates = sorted(output_dir.glob("*.mxl")) + sorted(output_dir.glob("*.musicxml")) + sorted(output_dir.glob("*.xml"))
    if not candidates:
        raise RuntimeError("Audiveris 没有生成 MusicXML；请换用更清晰、方向正确的乐谱图片")
    return candidates[0]

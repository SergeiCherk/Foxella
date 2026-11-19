"""The USDA import (db/usda.py) and the shipped food_sources.csv."""

import csv
import subprocess
import sys
from pathlib import Path

import pytest

from nutrition_bot.config import PROJECT_ROOT
from nutrition_bot.db.seed import FOODS_CSV, load_foods
from nutrition_bot.db.usda import (
    FIELDS,
    SOURCE_COLUMNS,
    Source,
    UsdaImportError,
    load_sources,
    read_rows,
    read_usda,
    refresh_rows,
    write_rows,
)

SR_DIR = PROJECT_ROOT / "data" / "usda" / "FoodData_Central_sr_legacy_food_csv_2018-04"


def row(code: str, kcal: str = "100", **extra: str) -> dict[str, str]:
    base = {"code": code, "raw_code": "", "yield_factor": "", "kcal_100": kcal}
    grams = {"protein_100": "1.0", "fat_100": "1.0", "carb_100": "1.0", "fiber_100": "1.0"}
    return {**base, **grams, **extra}


def src(code: str, source: str, *ids: str) -> Source:
    return Source(code, source, ids, "")


def usda_values(kcal: float, p: float = 10, f: float = 5, c: float = 20, fib: float | None = 2):
    values = {"kcal_100": kcal, "protein_100": p, "fat_100": f, "carb_100": c}
    return values | ({} if fib is None else {"fiber_100": fib})


# --- the shipped data -------------------------------------------------------------------


def test_every_food_has_exactly_one_source() -> None:
    sources = load_sources()
    assert set(sources) == {f.code for f in load_foods()}


def test_derived_is_used_only_for_cooked_grains_and_legumes() -> None:
    foods = {f.code: f for f in load_foods()}
    for code, source in load_sources().items():
        if source.source == "derived":
            assert foods[code].state == "cooked", code
            assert foods[code].category in {"grain", "legume"}, code


def test_derived_foods_equal_raw_divided_by_yield() -> None:
    """Water adds no nutrients: a cooked grain is its raw grain spread over yield_factor grams."""
    foods = {f.code: f for f in load_foods()}
    for code, source in load_sources().items():
        if source.source != "derived":
            continue
        food = foods[code]
        assert food.raw_code is not None
        assert food.yield_factor is not None
        raw = foods[food.raw_code]
        # Values are rounded (kcal to 1, grams to 0.1): allow half a step plus float noise.
        assert food.kcal_100 == pytest.approx(raw.kcal_100 / food.yield_factor, abs=0.5001), code
        for field in ("protein_100", "fat_100", "carb_100", "fiber_100"):
            expected = getattr(raw, field) / food.yield_factor
            assert getattr(food, field) == pytest.approx(expected, abs=0.0501), (code, field)


@pytest.mark.skipif(not SR_DIR.is_dir(), reason="USDA SR Legacy download is not present")
def test_foods_csv_is_up_to_date_with_the_usda_download() -> None:
    sources = load_sources()
    usda = read_usda(SR_DIR, {i for s in sources.values() for i in s.fdc_ids})
    _, rows = read_rows(FOODS_CSV)
    _, changes = refresh_rows(rows, sources, usda)
    assert changes == []


def test_writing_the_rows_back_keeps_foods_csv_byte_for_byte(tmp_path: Path) -> None:
    columns, rows = read_rows(FOODS_CSV)
    copy = tmp_path / "foods.csv"
    write_rows(copy, columns, rows)
    assert copy.read_bytes() == FOODS_CSV.read_bytes()


# --- refresh_rows -----------------------------------------------------------------------


def test_usda_mix_derived_and_label_rows() -> None:
    rows = [
        row("raw", "999"),
        row("cooked", "1", raw_code="raw", yield_factor="2.5"),
        row("mix"),
        row("pack", "55"),
    ]
    sources = {
        "raw": src("raw", "usda", "1"),
        "cooked": src("cooked", "derived"),
        "mix": src("mix", "usda_mix", "2", "3"),
        "pack": src("pack", "label"),
    }
    usda = {"1": usda_values(350, p=10.0), "2": usda_values(20), "3": usda_values(41)}
    new, changes = refresh_rows(rows, sources, usda)
    by_code = {r["code"]: r for r in new}
    assert by_code["raw"]["kcal_100"] == "350"
    assert by_code["cooked"]["kcal_100"] == "140"  # derived from the *new* raw value
    assert by_code["cooked"]["protein_100"] == "4.0"
    assert by_code["mix"]["kcal_100"] == "31"  # (20 + 41) / 2 = 30.5, rounded half up
    assert by_code["pack"] == rows[3]  # label rows are never touched
    assert [r["code"] for r in new] == ["raw", "cooked", "mix", "pack"]  # order kept
    assert {c.code for c in changes} == {"raw", "cooked", "mix"}


def test_unchanged_values_give_no_changes() -> None:
    rows = [row("a", "350", protein_100="10.0", fat_100="5.0", carb_100="20.0", fiber_100="2.0")]
    _, changes = refresh_rows(rows, {"a": src("a", "usda", "1")}, {"1": usda_values(350)})
    assert changes == []


def test_missing_fibre_counts_as_zero() -> None:
    new, _ = refresh_rows([row("fish")], {"fish": src("fish", "usda", "1")},
                          {"1": usda_values(80, fib=None)})  # fmt: skip
    assert new[0]["fiber_100"] == "0.0"


def test_missing_calories_are_an_error() -> None:
    values = usda_values(80)
    del values["kcal_100"]
    with pytest.raises(UsdaImportError, match="kcal_100 is missing"):
        refresh_rows([row("a")], {"a": src("a", "usda", "1")}, {"1": values})


def test_foods_and_sources_must_list_the_same_codes() -> None:
    with pytest.raises(UsdaImportError, match=r"missing \['b'\], unknown \['c'\]"):
        refresh_rows([row("a"), row("b")], {"a": src("a", "label"), "c": src("c", "label")}, {})


def test_derived_needs_a_raw_food_and_a_yield() -> None:
    with pytest.raises(UsdaImportError, match="derived needs raw_code"):
        refresh_rows([row("a")], {"a": src("a", "derived")}, {})


# --- load_sources and read_usda ---------------------------------------------------------


def write_sources(path: Path, *lines: str, header: str = ",".join(SOURCE_COLUMNS)) -> Path:
    path.write_text("\n".join([header, *lines]) + "\n", encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("a,guess,,", "unknown source"),
        ("a,usda,,", "usda needs 1..1 fdc_ids"),
        ("a,usda_mix,1,", "usda_mix needs 2..9"),
        ("a,label,1,", "label needs 0..0"),
        ("a,usda,12x,", "must be numbers"),
    ],
)
def test_bad_source_lines_are_rejected(tmp_path: Path, line: str, message: str) -> None:
    with pytest.raises(UsdaImportError, match=message):
        load_sources(write_sources(tmp_path / "s.csv", line))


def test_duplicate_codes_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(UsdaImportError, match=r"s\.csv:3: duplicate code"):
        load_sources(write_sources(tmp_path / "s.csv", "a,label,,", "a,label,,"))


def test_wrong_columns_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(UsdaImportError, match="expected columns"):
        load_sources(write_sources(tmp_path / "s.csv", header="code,source"))


def write_nutrients(sr_dir: Path) -> Path:
    sr_dir.mkdir()
    with (sr_dir / "food_nutrient.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "fdc_id", "nutrient_id", "amount"])
        writer.writerows([["1", "7", "1008", "52"], ["2", "7", "1003", "0.26"],
                          ["3", "7", "1093", "1.0"], ["4", "8", "1008", "99"]])  # fmt: skip
    return sr_dir


def test_read_usda_keeps_only_wanted_records_and_nutrients(tmp_path: Path) -> None:
    usda = read_usda(write_nutrients(tmp_path / "sr"), {"7"})
    assert usda == {"7": {"kcal_100": 52.0, "protein_100": 0.26}}


def test_read_usda_reports_unknown_records(tmp_path: Path) -> None:
    with pytest.raises(UsdaImportError, match="fdc_ids not in sr: 9"):
        read_usda(write_nutrients(tmp_path / "sr"), {"7", "9"})


def test_read_usda_explains_a_missing_download(tmp_path: Path) -> None:
    with pytest.raises(UsdaImportError, match="download the SR Legacy CSV"):
        read_usda(tmp_path, {"7"})


def test_fields_are_the_nutrient_columns_of_foods_csv() -> None:
    columns, _ = read_rows(FOODS_CSV)
    assert all(field in columns for field in FIELDS)


def test_script_without_the_download_fails_with_a_clear_message(tmp_path: Path) -> None:
    script = PROJECT_ROOT / "scripts" / "import_usda.py"
    result = subprocess.run(
        [sys.executable, str(script), "--sr-dir", str(tmp_path)],
        capture_output=True, text=True, cwd=PROJECT_ROOT, check=False,
    )  # fmt: skip
    assert result.returncode == 1
    assert "download the SR Legacy CSV" in result.stdout

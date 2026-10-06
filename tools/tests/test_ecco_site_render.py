#!/usr/bin/env python3
"""Regression suite: tools/ecco_site_render.py renders a site copy by EXACT rules and fails closed on anything else.

  [1] site file validation (schema, unknown keys, slug / MPAN shapes, duplicates, self-maps)
  [2] the exact rules on synthetic text: entity ids per domain, quoted slug, ESPHome services and firmware names kept, kept entities,
      entity_map at entity-id boundaries, Octopus ids, unexpected contexts and stray placeholders refused, overlap refused
  [3] the real tree: the default site renders the identity, a custom slug renders every dongle entity and nothing else, the render is
      deterministic, a rendered tree is refused as input (no double render), missing source tokens are refused
  [4] output safety: --dry-run / --diff write nothing; --out inside the repo must be under dist/; a foreign non-empty dir is refused
  [5] the tracked example site file is valid and the local site file is git-ignored

Synthetic values only (no real site value). Test-only, no network. I/O: reads the repo, writes only under a temp dir.
"""

from __future__ import annotations

import contextlib
import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import ecco_site_render as R  # noqa: E402
import yaml  # noqa: E402

sys.path.insert(0, str(ROOT / "registry" / "tests"))
import _pub0_scope as P  # noqa: E402

_TMP = tempfile.TemporaryDirectory()


def public_root() -> Path:
    """The generic tree to render: this tree in the public export; in the private development tree (whose deployable files carry
    the owner's site values) a temp copy of the render set built with pub0's exact forward() - the text the export ships."""
    if P.EXPORTED:
        return ROOT
    dst = Path(_TMP.name) / "public"
    for rel in [*R.render_set(ROOT), R.FIRMWARE_REL]:
        (dst / rel).parent.mkdir(parents=True, exist_ok=True)
        if P.is_target(rel):
            (dst / rel).write_text(P.forward(rel, P.read_repo(rel)), encoding="utf-8", newline="\n")
        else:
            shutil.copyfile(ROOT / rel, dst / rel)
    return dst


PUB = public_root()
print(f"  info  rendering {'this tree (the public export)' if P.EXPORTED else 'the pub0 export of this private tree (built in a temp dir)'}")

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def refused(fn) -> bool:
    try:
        fn()
    except R.RenderError:
        return True
    return False


def site(**kw) -> R.Site:
    return R.parse_site({"schema": R.SCHEMA, "device_slug": "ecco_clock_dongle", **kw})


# Synthetic tariff values (shape-valid, not anyone's meter).
OCTO = {"meter_serial": "00x0000001", "import_mpan": "1" + "0" * 11 + "1", "export_mpan": "1" + "0" * 11 + "2"}
ACTIONS = ("fallback_profile_execute", "ha_supervision_heartbeat")

# ===========================================================================
print("[1] site file validation")
# ===========================================================================
check("a minimal site file parses to the generic defaults", site() == R.Site())
for bad, why in [({}, "no schema"), ({"schema": "ecco-site/2", "device_slug": "x_y"}, "wrong schema"),
                 ({"schema": R.SCHEMA}, "no slug"), ({"schema": R.SCHEMA, "device_slug": "a", "extra": 1}, "unknown key"),
                 ({"schema": R.SCHEMA, "device_slug": "Ecco"}, "upper case"), ({"schema": R.SCHEMA, "device_slug": "ecco-dongle"}, "hyphen"),
                 ({"schema": R.SCHEMA, "device_slug": "a__b"}, "double underscore"), ({"schema": R.SCHEMA, "device_slug": "../x"}, "path"),
                 ({"schema": R.SCHEMA, "device_slug": ""}, "empty"), ({"schema": R.SCHEMA, "device_slug": "x_"}, "trailing underscore"),
                 ({"schema": R.SCHEMA, "device_slug": "a_b", "octopus": {"meter_serial": "00x0000001"}}, "partial octopus"),
                 ({"schema": R.SCHEMA, "device_slug": "a_b", "octopus": {**OCTO, "import_mpan": "123"}}, "short MPAN"),
                 ({"schema": R.SCHEMA, "device_slug": "a_b", "octopus": {**OCTO, "export_mpan": OCTO["import_mpan"]}}, "same MPAN"),
                 ({"schema": R.SCHEMA, "device_slug": "a_b", "octopus": {**OCTO, "meter_serial": "AB-12"}}, "bad serial"),
                 ({"schema": R.SCHEMA, "device_slug": "a_b", "octopus": {**OCTO, "x": 1}}, "unknown octopus key"),
                 ({"schema": R.SCHEMA, "device_slug": "a_b", "keep_default_slug_entities": ["sensor.other_x"]}, "keep not a dongle id"),
                 ({"schema": R.SCHEMA, "device_slug": "a_b", "keep_default_slug_entities": ["sensor.ecco_clock_dongle_x"] * 2}, "dup keep"),
                 ({"schema": R.SCHEMA, "device_slug": "a_b", "entity_map": {"sensor.a": "sensor.a"}}, "self map"),
                 ({"schema": R.SCHEMA, "device_slug": "a_b", "entity_map": {"sensor.a": "not an id"}}, "bad map target"),
                 ([], "not a mapping")]:
    check(f"refused: {why}", refused(lambda b=bad: R.parse_site(b)))

# ===========================================================================
print("")
print("[2] the exact rules (synthetic text)")
# ===========================================================================
S = site(device_slug="home_dongle")
txt = ("a: sensor.ecco_clock_dongle_soc\nb: binary_sensor.ecco_clock_dongle_ok\nc: number.ecco_clock_dongle_x\n"
       "d: - switch.ecco_clock_dongle_*\n# the default slug is `ecco_clock_dongle`\n"
       "e: esphome.ecco_clock_dongle_fallback_profile_execute\nf: 'ecco_clock_dongle_ha_supervision_heartbeat'\n"
       "g: firmware/ecco_clock_dongle_stage3_4_free_power.yaml\n")
out, counts = R.render_text("t.yaml", txt, S, ACTIONS)
check("entity ids of every domain render to the site slug (globs included)",
      "sensor.home_dongle_soc" in out and "binary_sensor.home_dongle_ok" in out and "number.home_dongle_x" in out
      and "switch.home_dongle_*" in out and counts.get("entity") == 4, str(counts))
check("the quoted slug (documentation) renders", "`home_dongle`" in out and counts.get("quoted") == 1)
check("ESPHome action service names and firmware file names are KEPT (node name, not the HA device slug)",
      "esphome.ecco_clock_dongle_fallback_profile_execute" in out and "'ecco_clock_dongle_ha_supervision_heartbeat'" in out
      and "firmware/ecco_clock_dongle_stage3_4_free_power.yaml" in out and counts.get("service_kept") == 2
      and counts.get("firmware_name_kept") == 1)
check("the default site renders the identity", R.render_text("t.yaml", txt, site(), ACTIONS)[0] == txt)
o2, c2 = R.render_text("t.yaml", "x: sensor.ecco_clock_dongle_wifi_signal\ny: sensor.ecco_clock_dongle_soc\n",
                       site(device_slug="home_dongle", keep_default_slug_entities=["sensor.ecco_clock_dongle_wifi_signal"]), ACTIONS)
check("keep_default_slug_entities keeps exactly those ids", o2 == "x: sensor.ecco_clock_dongle_wifi_signal\ny: sensor.home_dongle_soc\n"
      and c2.get("kept_entity") == 1, o2)
o3, _ = R.render_text("t.yaml", "a: sensor.solar_today\nb: sensor.solar_today_x\nc: xsensor.solar_today\nd: sensor.ecco_clock_dongle_soc\n",
                      site(entity_map={"sensor.solar_today": "sensor.pv_today", "sensor.ecco_clock_dongle_soc": "sensor.bms_soc"}), ACTIONS)
check("entity_map renames whole entity ids only (no prefix / suffix match), dongle ids included",
      o3 == "a: sensor.pv_today\nb: sensor.solar_today_x\nc: xsensor.solar_today\nd: sensor.bms_soc\n", o3)
oc = "s: sensor.octopus_energy_electricity_your_meter_serial_your_import_mpan_current_rate\nt: sensor.octopus_energy_electricity_your_meter_serial_your_export_mpan_export_current_rate\n"
o4, c4 = R.render_text("t.yaml", oc, site(octopus=OCTO), ACTIONS)
check("Octopus ids render serial + the right MPAN per direction",
      o4 == oc.replace("your_meter_serial_your_import_mpan", "00x0000001_" + OCTO["import_mpan"])
              .replace("your_meter_serial_your_export_mpan", "00x0000001_" + OCTO["export_mpan"]) and c4.get("octopus") == 2, o4)
check("without an octopus block the placeholders stay generic (and are counted)",
      R.render_text("t.yaml", oc, site(), ACTIONS) == (oc, {"octopus_placeholder_left": 2}))
for bad, why in [("x: my_ecco_clock_dongle_soc\n", "a prefixed (already rendered) slug"),
                 ("x: sensor.kitchen_ecco_clock_dongle_soc\nsensor.ecco_clock_dongle_y\n", "an area-prefixed slug next to a valid one"),
                 ("x: ecco_clock_dongle_soc\n", "a bare slug with no domain"),
                 ("x: notadomain.ecco_clock_dongle_soc\n", "an unknown domain"),
                 ("x: esphome.ecco_clock_dongle_unknown_action\n", "an action the firmware does not declare"),
                 ("x: your_meter_serial\n", "a stray tariff placeholder"),
                 ("x: \"ecco_clock_dongle'\n", "mismatched quotes")]:
    check(f"refused: {why}", refused(lambda b=bad: R.render_text("t.yaml", b, site(device_slug="home_dongle", octopus=OCTO), ACTIONS)))
check("a mapped dongle id is renamed once, not also slug-rendered",
      R.render_text("t.yaml", "a: sensor.ecco_clock_dongle_soc\n",
                    site(entity_map={"sensor.ecco_clock_dongle_soc": "sensor.b"}, device_slug="home_dongle"), ACTIONS)[0] == "a: sensor.b\n")
check("refused: overlapping sites (two mappings of the same text)",
      refused(lambda: R.render_text("t.yaml", "a: sensor.x\n", R.Site(entity_map=(("sensor.x", "sensor.y"), ("sensor.x", "sensor.z"))),
                                    ACTIONS)))


def _mini_tree(td: str, files: dict) -> Path:
    root = Path(td) / "mini"
    for rel, text in {R.FIRMWARE_REL: (PUB / R.FIRMWARE_REL).read_text(encoding="utf-8"), **files}.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8", newline="\n")
    return root


# ===========================================================================
print("")
print("[3] the real tree")
# ===========================================================================
ident, rep0 = R.render_tree(PUB, site())
check("the render set is the deployable files (HA packages + dashboard + InfluxDB + card assets/examples + site tools), not tests/docs",
      len(ident) >= 30 and "home-assistant/dashboards/ecco_pro.yaml" in ident and "deployment/ha-manifest.yaml" in ident
      and not any(r.startswith(("registry/", "docs/")) or "/tests/" in r or "/test/" in r for r in ident), str(len(ident)))
check("the default site renders the identity for every file", all(a == b for a, b in ident.values()))
custom, rep = R.render_tree(PUB, site(device_slug="home_dongle", octopus=OCTO))
n_entities = sum(r.sites.get("entity", 0) for r in rep)
changed = [rel for rel, (a, b) in custom.items() if a != b]
check("a custom slug renders every dongle entity site (hundreds) across the packages / dashboard / InfluxDB / tools",
      n_entities > 500 and "home-assistant/dashboards/ecco_pro.yaml" in changed, str(n_entities))
check("after a custom render no default-slug entity id is left, except the ESPHome service names and firmware file names",
      all(not any(f"{d}.ecco_clock_dongle_".encode() in b for d in R.DOMAINS) for _a, b in custom.values()))
check("after a render with an octopus block no tariff placeholder is left",
      all(not any(p.encode() in b for p in R.OCTOPUS_PLACEHOLDERS) for _a, b in custom.values()))
again, _ = R.render_tree(PUB, site(device_slug="home_dongle", octopus=OCTO))
check("the render is deterministic (byte-identical twice)", again == custom)
with tempfile.TemporaryDirectory() as td:
    tmp = _mini_tree(td, {rel: custom[rel][1].decode("utf-8") for rel in R.render_set(PUB)})
    check("a rendered tree is refused as input (no double render: its slug sites are not the generic token)",
          refused(lambda: R.render_tree(tmp, site(device_slug="other_dongle"))))
with tempfile.TemporaryDirectory() as td:
    tmp = _mini_tree(td, {"home-assistant/packages/x.yaml": "a: input_number.unrelated\n"})
    check("a slug that matches nothing is refused (expected source token missing)",
          refused(lambda: R.render_tree(tmp, site(device_slug="home_dongle"))) and R.render_tree(tmp, site())[0])
    check("octopus values with no placeholder id anywhere are refused (expected source token missing)",
          refused(lambda: R.render_tree(tmp, site(octopus=OCTO))))
    check("a firmware that declares no API action is refused (service names are never guessed)",
          (tmp / R.FIRMWARE_REL).write_text("esphome:\n  name: x\n", encoding="utf-8") > 0 and refused(lambda: R.render_tree(tmp, site())))
check("an entity_map source that occurs nowhere is refused",
      refused(lambda: R.render_tree(PUB, site(entity_map={"sensor.does_not_exist_anywhere": "sensor.x"}))))
check("a kept entity that occurs nowhere is refused",
      refused(lambda: R.render_tree(PUB, site(device_slug="home_dongle", keep_default_slug_entities=["sensor.ecco_clock_dongle_nope"]))))

# ===========================================================================
print("")
print("[4] output safety")
# ===========================================================================
with tempfile.TemporaryDirectory() as td:
    sf = Path(td) / "site.yaml"
    sf.write_text(yaml.safe_dump({"schema": R.SCHEMA, "device_slug": "ecco_clock_dongle"}), encoding="utf-8")
    out = Path(td) / "out"
    with contextlib.redirect_stdout(io.StringIO()):
        rc_dry = R.main(["--site", str(sf), "--root", str(PUB), "--out", str(out), "--dry-run"])
        rc_diff = R.main(["--site", str(sf), "--root", str(PUB), "--out", str(out), "--diff"])
    check("--dry-run and --diff exit 0 and write nothing", rc_dry == 0 and rc_diff == 0 and not out.exists())
    with contextlib.redirect_stdout(io.StringIO()):
        rc = R.main(["--site", str(sf), "--root", str(PUB), "--out", str(out)])
    check("a real run writes the render set plus the marker", rc == 0 and (out / R.MARKER).is_file()
          and (out / "home-assistant/dashboards/ecco_pro.yaml").is_file())
    with contextlib.redirect_stdout(io.StringIO()):
        rc2 = R.main(["--site", str(sf), "--root", str(PUB), "--out", str(out)])
    check("a previous render (marker present) is replaced", rc2 == 0)
    foreign = Path(td) / "foreign"
    foreign.mkdir()
    (foreign / "keep.txt").write_text("x", encoding="utf-8")
    with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
        rc3 = R.main(["--site", str(sf), "--root", str(PUB), "--out", str(foreign)])
    check("a non-empty directory that is not a previous render is refused and left untouched",
          rc3 == 2 and (foreign / "keep.txt").read_text(encoding="utf-8") == "x" and len(list(foreign.iterdir())) == 1)
    check("--out inside the repository but outside dist/ is refused", refused(lambda: R._safe_out(ROOT / "home-assistant", ROOT)))
    check("--out under the repository's dist/ is accepted", R._safe_out(ROOT / "dist" / "site-test-never-written", ROOT) is not None)
    bad = Path(td) / "bad.yaml"
    bad.write_text("schema: ecco-site/1\ndevice_slug: Bad-Slug\n", encoding="utf-8")
    with contextlib.redirect_stderr(io.StringIO()):
        check("an invalid site file exits 2 (refused) without writing", R.main(["--site", str(bad), "--root", str(PUB), "--out", str(Path(td) / "o2")]) == 2
              and not (Path(td) / "o2").exists())

# ===========================================================================
print("")
print("[5] the example and the local site file")
# ===========================================================================
ex = yaml.safe_load((ROOT / "ecco_site.example.yaml").read_text(encoding="utf-8"))
check("ecco_site.example.yaml is a valid site file with the generic defaults", R.parse_site(ex) == R.Site())
ign = subprocess.run(["git", "check-ignore", "-q", "--no-index", "ecco_site.local.yaml"], cwd=str(ROOT))
ign2 = subprocess.run(["git", "check-ignore", "-q", "--no-index", "dist/site/x.yaml"], cwd=str(ROOT))
check("ecco_site.local.yaml and dist/site/ are git-ignored (site values never get tracked)", ign.returncode == 0 and ign2.returncode == 0)

print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All site-render checks passed.")

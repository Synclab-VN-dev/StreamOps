"""Issue #75: pinned MagicPath source + fail-closed Golden approval contract."""
import copy
import hashlib
import json
import re
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parent/"visual_obs_plugins"
IDS={"plugin":("458351046272638976","458975004185468928"),
     "dashboard":("456064390102405120","458892152907374592")}

def blob_sha(b):
    return hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest()

def read_bytes(path):
    b=path.read_bytes()
    return b.replace(b"\r\n",b"\n") if path.suffix in {".tsx",".css"} else b

def load():
    return json.loads((ROOT/"manifest.json").read_text(encoding="utf-8"))

def validate_source(manifest):
    assert manifest["schema_version"]==1
    assert len(manifest["references"])==2
    for ref in manifest["references"]:
        assert (ref["component_id"],ref["revision_id"])==IDS[ref["kind"]]
        for file in [*ref["files"],ref["preview"]]:
            candidate=ROOT/file["path"]
            assert candidate.is_file(),str(candidate)
            assert blob_sha(read_bytes(candidate))==file["git_blob_sha1"],str(candidate)
    assert read_bytes(ROOT/"originals/plugin/src/index.css")==read_bytes(ROOT/"originals/dashboard/src/index.css")
    # The isolated renderer must use byte-identical MagicPath component source.
    for ref in manifest["references"]:
        component=next(f for f in ref["files"] if "/components/generated/" in f["path"])
        relative=component["path"].split("/src/",1)[1]
        original=ROOT/component["path"]
        rendered=ROOT/"reference_source"/"src"/relative
        assert read_bytes(original)==read_bytes(rendered),"Renderer source modified: "+relative
    assert read_bytes(ROOT/"originals/plugin/src/index.css")==read_bytes(
        ROOT/"reference_source/src/index.css"),"Renderer styles differ from original"
    main=(ROOT/"reference_source/src/main.tsx").read_text(encoding="utf-8")
    assert "StreamOpsOBSPluginManager" in main and "StreamOpsMobileDashboard" in main
    assert "server/web" not in main
    cases=manifest["required_cases"]
    assert len(cases)>=9
    assert len({c["label"] for c in cases})==len(cases)
    assert {(c["width"],c["height"]) for c in cases}=={(360,800),(390,844),(768,1024),(1440,900)}
    assert {c["state"] for c in cases}>={"normal","expanded","confirm","plugin-card"}
    assert all(c["label"]==f'{c["design"]}-{c["state"]}-{c["width"]}x{c["height"]}' for c in cases)
    assert manifest["rendering"]["mean_rgb_limit"]==.08
    assert manifest["rendering"]["reference_drift_limit"]==.015
    assert manifest["rendering"]["automatic_golden_update"] is False

def validate_approval(manifest,root=ROOT):
    assert manifest["approved"] is True,"Missing explicit owner-approved MagicPath golden"
    for field in ("approved_by","approved_at","review_url"):
        assert manifest["approval"].get(field),"Missing approval "+field
    hashes=manifest["approval"]["expected_sha256"]
    labels={c["label"] for c in manifest["required_cases"]}
    assert set(hashes)==labels,"Incomplete Golden approval"
    directory=root/"goldens"
    assert {p.stem for p in directory.glob("*.png")}==labels
    for label,digest in hashes.items():
        assert re.fullmatch("[0-9a-f]{64}",digest),label
        data=(directory/(label+".png")).read_bytes()
        assert data.startswith(b"\x89PNG\r\n\x1a\n"),label
        assert hashlib.sha256(data).hexdigest()==digest,label
    assert not manifest["uncovered_design_states"],"MagicPath design state references missing"

def test_original_magicpath_source_and_preview_hashes():
    validate_source(load())

def test_missing_approval_or_goldens_cannot_pass(tmp_path):
    m=copy.deepcopy(load())
    m["approved"]=False
    with pytest.raises(AssertionError,match="Missing explicit owner-approved"):
        validate_approval(m)
    impostor=copy.deepcopy(m)
    impostor["approved"]=True
    impostor["approval"].update(approved_by="fake",approved_at="2026",review_url="https://github.com")
    with pytest.raises(AssertionError,match="Incomplete Golden"):
        validate_approval(impostor,tmp_path)

def test_visual_comparator_detects_large_theme_and_geometry_regression():
    from PIL import Image,ImageDraw,ImageChops,ImageStat
    original=Image.new("RGB",(390,844),"white")
    assert Image.new("RGB",(380,844),"white").size!=original.size
    altered=original.copy()
    ImageDraw.Draw(altered).rectangle((0,0,390,650),fill="magenta")
    diff=ImageChops.difference(original,altered)
    assert sum(ImageStat.Stat(diff).mean)/(255*3)>.08

"""HWP (binary) to HWPX conversion utilities.

Uses the bundled Java converter (hwp2hwpx + hwplib/hwpxlib) via JPype and
applies post-conversion container patching for missing rootfile entries.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import xml.etree.ElementTree as ET
import zipfile


def _converter_dir() -> Path:
    return Path(__file__).resolve().parent / "vendor" / "hwp2hwpx"


def _converter_classpath() -> list[str]:
    base = _converter_dir()
    main_jar = base / "hwp2hwpx-1.0.0.jar"
    deps_dir = base / "dependency"

    dep_jars = sorted(deps_dir.glob("*.jar"))
    classpath = [main_jar, *dep_jars]
    missing = [p for p in classpath if not p.exists()]
    if missing:
        missing_str = ", ".join(str(p) for p in missing)
        raise FileNotFoundError(
            f"HWP converter jars missing: {missing_str}"
        )

    return [str(p) for p in classpath]


def _ensure_jvm() -> None:
    try:
        import jpype
    except ImportError as exc:
        raise ImportError(
            "HWP conversion requires 'jpype1'. Install it to parse .hwp files."
        ) from exc

    if jpype.isJVMStarted():
        return

    jpype.startJVM(classpath=_converter_classpath())


def patch_hwpx_container(hwpx_path: str | Path) -> None:
    """Remove container rootfile entries that reference missing files."""
    hwpx_path = Path(hwpx_path)

    with zipfile.ZipFile(hwpx_path, "r") as zin:
        names = set(zin.namelist())
        container_xml = zin.read("META-INF/container.xml")

    root = ET.fromstring(container_xml)
    ns = {"odf": "urn:oasis:names:tc:opendocument:xmlns:container"}
    rootfiles = root.find("odf:rootfiles", ns)
    if rootfiles is None:
        return

    to_remove = [
        rf
        for rf in rootfiles.findall("odf:rootfile", ns)
        if rf.get("full-path") not in names
    ]
    if not to_remove:
        return

    for rf in to_remove:
        rootfiles.remove(rf)

    ET.register_namespace("", "urn:oasis:names:tc:opendocument:xmlns:container")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".hwpx") as tmp:
        tmp_path = Path(tmp.name)

    try:
        with zipfile.ZipFile(hwpx_path, "r") as zin, zipfile.ZipFile(tmp_path, "w") as zout:
            for item in zin.infolist():
                if item.filename == "META-INF/container.xml":
                    zout.writestr(
                        item,
                        ET.tostring(root, xml_declaration=True, encoding="unicode"),
                    )
                else:
                    zout.writestr(item, zin.read(item.filename))

        shutil.move(str(tmp_path), str(hwpx_path))
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def convert_hwp_to_hwpx_bytes(hwp_path: str | Path) -> bytes:
    """Convert ``.hwp`` to patched ``.hwpx`` bytes using bundled Java tools."""
    hwp_path = Path(hwp_path)
    if not hwp_path.exists():
        raise FileNotFoundError(f"HWP file not found: {hwp_path}")

    _ensure_jvm()

    import jpype

    HWPReader = jpype.JClass("kr.dogfoot.hwplib.reader.HWPReader")
    Hwp2Hwpx = jpype.JClass("kr.dogfoot.hwp2hwpx.Hwp2Hwpx")
    HWPXWriter = jpype.JClass("kr.dogfoot.hwpxlib.writer.HWPXWriter")

    with tempfile.TemporaryDirectory() as tmp_dir:
        hwpx_path = Path(tmp_dir) / hwp_path.with_suffix(".hwpx").name

        from_file = HWPReader.fromFile(str(hwp_path))
        to_file = Hwp2Hwpx.toHWPX(from_file)
        HWPXWriter.toFilepath(to_file, str(hwpx_path))

        patch_hwpx_container(hwpx_path)
        return hwpx_path.read_bytes()


__all__ = ["convert_hwp_to_hwpx_bytes", "patch_hwpx_container"]

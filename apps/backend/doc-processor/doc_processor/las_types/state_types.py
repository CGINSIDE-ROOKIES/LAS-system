from pydantic import BaseModel, Field, computed_field

from pathlib import Path
from typing import Literal, Annotated

from .ir_types import IRGroup


class DocumentState(BaseModel):  # Main graph state
    target_file: Path = Field(default=Path())  # kind temp.
    ir_groups: list[IRGroup] = Field(default=[])

    # doc may hold other doctype isntances, also due to serialization issues, not used
    # doc: Any = Field(default=None)  # HwpxDocument

    # used as a collector (for concurrent workers) before re-indexing
    # empty list [] acts as a clear signal (operator.add would silently keep old items)
    ir_groups_temp: Annotated[
            list[tuple[int, IRGroup]],
            lambda left, right: [] if right == [] else left + right
        ] = Field(default=[])

    # used for preprocess routing / notifying state
    preprocess_state: Literal["uncategorized", "prelim", "finished"] = Field(default="uncategorized")

    @computed_field
    def formatted_content(self) -> list[str]:
        assert self.ir_groups, "ir_groups needs to be inserted/generated!"
        return [grp.formatted_str for grp in self.ir_groups]
    
    @classmethod
    def from_file(cls, file_path: Path):
        match file_path.suffix:
            case ".hwpx":
                return cls.from_hwpx(file_path)
            case ".hwp":
                return cls.from_hwp(file_path)
            case ".docx":
                return cls.from_docx(file_path)
            case ".pdf":
                raise NotImplementedError()
            case _:
                raise TypeError(f"Unsuppoerted file extension: {file_path}")

    @classmethod
    def from_hwpx(cls, file_path: Path):
        from hwpx import HwpxDocument
        from ..core.ir import create_ir_dict, ir_grouper
        with HwpxDocument.open(file_path) as doc:
            ir_mappings = create_ir_dict(doc)
            ir_groups = ir_grouper(ir_mappings)
            return cls(
                target_file=file_path,
                ir_groups=ir_groups,
            )

    @classmethod
    def from_hwp(cls, file_path: Path):
        print("== converting from hwp to hwpx... ==")
        import jpype
        import tempfile

        hwp2hwpx_jar = Path(__file__).resolve().parents[1] / "vendor/hwp2hwpx/hwp2hwpx-1.0.0.jar"
        deps_dir = Path(__file__).resolve().parents[1] / "vendor/hwp2hwpx/dependency/*"

        if not jpype.isJVMStarted():
            jpype.startJVM(classpath=[str(hwp2hwpx_jar), str(deps_dir)])

        HWPReader = jpype.JClass("kr.dogfoot.hwplib.reader.HWPReader")
        Hwp2Hwpx = jpype.JClass("kr.dogfoot.hwp2hwpx.Hwp2Hwpx")
        HWPXWriter = jpype.JClass("kr.dogfoot.hwpxlib.writer.HWPXWriter")

        with tempfile.TemporaryDirectory() as tmp_dir:
            hwpx_path = Path(tmp_dir) / file_path.with_suffix(".hwpx").name
            from_file = HWPReader.fromFile(str(file_path))
            to_file = Hwp2Hwpx.toHWPX(from_file)
            HWPXWriter.toFilepath(to_file, str(hwpx_path))
            cls._patch_hwpx_container(hwpx_path)
            return cls.from_hwpx(hwpx_path)

    @staticmethod
    def _patch_hwpx_container(hwpx_path: Path):
        """Remove rootfile entries from container.xml that reference missing files in the zip."""
        import zipfile
        import xml.etree.ElementTree as ET
        import shutil
        import tempfile as _tmpfile

        with zipfile.ZipFile(hwpx_path, "r") as zin:
            names = set(zin.namelist())
            container_xml = zin.read("META-INF/container.xml")

        root = ET.fromstring(container_xml)
        ns = {"odf": "urn:oasis:names:tc:opendocument:xmlns:container"}
        rootfiles = root.find("odf:rootfiles", ns)
        if rootfiles is None:
            return

        to_remove = [
            rf for rf in rootfiles.findall("odf:rootfile", ns)
            if rf.get("full-path") not in names
        ]
        if not to_remove:
            return

        for rf in to_remove:
            rootfiles.remove(rf)

        ET.register_namespace("", "urn:oasis:names:tc:opendocument:xmlns:container")
        with _tmpfile.NamedTemporaryFile(delete=False, suffix=".hwpx") as tmp:
            tmp_path = Path(tmp.name)
        with zipfile.ZipFile(hwpx_path, "r") as zin, zipfile.ZipFile(tmp_path, "w") as zout:
            for item in zin.infolist():
                if item.filename == "META-INF/container.xml":
                    zout.writestr(item, ET.tostring(root, xml_declaration=True, encoding="unicode"))
                else:
                    zout.writestr(item, zin.read(item.filename))
        shutil.move(str(tmp_path), str(hwpx_path))

    @classmethod
    def from_docx(cls, file_path: Path):
        from ..core.docx_ir import export_docx_structured
        from ..core.ir import create_ir_dict_from_mapping, ir_grouper

        parsed = export_docx_structured(file_path)
        ir_mappings = create_ir_dict_from_mapping(parsed)
        ir_groups = ir_grouper(ir_mappings)
        return cls(
            target_file=file_path,
            ir_groups=ir_groups,
        )

    @classmethod
    def from_pdf(cls, file_path: Path):
        # exact mapping to OOXML Xpath (that the IR uses for ID) is not possible
        # needs a custom translator to at least mimick the translation to the IR
        # ID levels
        # - section (doesn't seem to work or have any meaning anyways, stuck at s1)
        # - paragraph
        # - runs: where the formatting change within a paragraph
        #           such as: changes in font/fontsize, italic/bold/underline and such
        ...


class IRGroupState(BaseModel):
    # IRGroup is put in a list and order should be maintained...
    # (needs design change for that or doesn't matter? 흠...)
    group_idx: int
    ir_group: IRGroup

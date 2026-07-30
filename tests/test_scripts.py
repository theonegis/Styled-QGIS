#!/usr/bin/env python3

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from apply_qgis_patch import patch_bundle, patch_cmake, patch_main
from resolve_versions import QGIS_RELEASE_RE, _select_release


class VersionResolverTests(unittest.TestCase):
    def test_qgis_uses_semver_not_release_time(self) -> None:
        releases = [
            {
                "tag_name": "final-3_44_12",
                "published_at": "2026-07-03T12:25:10Z",
                "draft": False,
                "prerelease": False,
            },
            {
                "tag_name": "final-4_2_0",
                "published_at": "2026-07-03T12:25:09Z",
                "draft": False,
                "prerelease": False,
            },
            {
                "tag_name": "final-4_0_3",
                "published_at": "2026-05-29T12:05:00Z",
                "draft": False,
                "prerelease": False,
            },
        ]
        selected = _select_release(
            "qgis/QGIS", releases, QGIS_RELEASE_RE, required_major=4
        )
        self.assertEqual(selected.tag, "final-4_2_0")


class PatchTests(unittest.TestCase):
    def test_patch_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src/app").mkdir(parents=True)
            main = root / "src/app/main.cpp"
            main.write_text(
                '  QString desiredStyle = settings.value( u"qgis/style"_s ).toString();\n'
                '  const QString theme = settings.value( u"UI/UITheme"_s ).toString();\n'
                '  if ( !desiredStyle.isEmpty() )\n'
                "  {",
                encoding="utf-8",
            )
            cmake = root / "CMakeLists.txt"
            cmake.write_text(
                "if (WITH_CORE)\n"
                "  include(VcpkgInstallDeps)\n"
                "  include(Bundle)\n"
                "endif()\n",
                encoding="utf-8",
            )
            bundle = root / "cmake/Bundle.cmake"
            bundle.parent.mkdir(parents=True)
            bundle.write_text(
                "if(CREATE_NSIS)\n"
                "  # There is a bug in NSI that does not handle full unix paths properly. Make\n"
                "endif()\n",
                encoding="utf-8",
            )

            patch_main(root)
            patch_cmake(root)
            patch_bundle(root)
            first_main = main.read_text(encoding="utf-8")
            first_cmake = cmake.read_text(encoding="utf-8")
            first_bundle = bundle.read_text(encoding="utf-8")
            patch_main(root)
            patch_cmake(root)
            patch_bundle(root)
            self.assertEqual(first_main, main.read_text(encoding="utf-8"))
            self.assertEqual(first_cmake, cmake.read_text(encoding="utf-8"))
            self.assertEqual(first_bundle, bundle.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

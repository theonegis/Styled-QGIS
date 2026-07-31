#!/usr/bin/env python3

from __future__ import annotations

import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from apply_qgis_patch import patch_cmake, patch_main
from prepare_ifw_package import PACKAGE_ID, prepare_ifw_package
from resolve_versions import QGIS_RELEASE_RE, _select_release


class WorkflowTests(unittest.TestCase):
    def test_remote_actions_use_full_commit_sha(self) -> None:
        workflows = Path(__file__).resolve().parents[1] / ".github/workflows"
        full_sha = re.compile(r"^[^/\s@]+/[^/\s@]+@[0-9a-f]{40}$")

        # 固定完整提交既能避免上游标签漂移，也能在推送前发现 SHA 截断。
        for workflow in workflows.glob("*.yml"):
            for line_number, line in enumerate(
                workflow.read_text(encoding="utf-8").splitlines(), start=1
            ):
                match = re.search(r"\buses:\s*(\S+)", line)
                if match is None or match.group(1).startswith("./"):
                    continue
                action = match.group(1)
                with self.subTest(workflow=workflow.name, line=line_number):
                    self.assertRegex(action, full_sha)

    def test_release_workflow_uses_verified_platform_packages(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github/workflows/build.yml"
        ).read_text(encoding="utf-8")
        self.assertGreaterEqual(workflow.count("-D WITH_QSCIAPI=OFF"), 2)
        self.assertIn("windows_build:", workflow)
        self.assertIn("windows_package:", workflow)
        self.assertIn("QtInstallerFramework/4.7/bin", workflow)
        self.assertIn("Silently install and verify QGIS+", workflow)
        self.assertIn("Verify bundled macOS application", workflow)
        self.assertNotIn("-D CREATE_NSIS=ON", workflow)

    def test_workflow_avoids_hosted_runner_warnings(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github/workflows/build.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("brew untap aws/tap || true", workflow)
        self.assertIn(
            "TheMrMilchmann/setup-msvc-dev@"
            "79dac248aac9d0059f86eae9d8b5bfab4e95e97c",
            workflow,
        )
        self.assertNotIn("ilammy/msvc-dev-cmd@", workflow)

    def test_windows_vcpkg_uses_runner_work_drive_without_binary_cache(
        self,
    ) -> None:
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github/workflows/build.yml"
        ).read_text(encoding="utf-8")
        windows_job = workflow.split("  windows_build:", 1)[1].split(
            "  windows_package:", 1
        )[0]

        self.assertIn(
            "$drive = Split-Path -Qualifier $env:RUNNER_TEMP",
            windows_job,
        )
        self.assertIn('VCPKG_ROOT=$vcpkgRoot', windows_job)
        self.assertIn('VCPKG_BUILDTREES_ROOT=$buildtreesRoot', windows_job)
        self.assertIn("VCPKG_BINARY_SOURCES: clear", windows_job)
        self.assertIn(
            "--x-buildtrees-root=${VCPKG_BUILDTREES_ROOT}",
            windows_job,
        )
        self.assertNotIn(
            "uses: ./upstream/QGIS/.github/actions/setup-vcpkg",
            windows_job,
        )
        self.assertNotIn("--x-buildtrees-root=C:/src", windows_job)
        self.assertNotIn("-D NUGET_TOKEN=", windows_job)


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

            patch_main(root)
            patch_cmake(root)
            first_main = main.read_text(encoding="utf-8")
            first_cmake = cmake.read_text(encoding="utf-8")
            patch_main(root)
            patch_cmake(root)
            self.assertEqual(first_main, main.read_text(encoding="utf-8"))
            self.assertEqual(first_cmake, cmake.read_text(encoding="utf-8"))


class QtIfwPackageTests(unittest.TestCase):
    def test_generates_valid_metadata_for_staged_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "ifw"
            runtime = output / "packages" / PACKAGE_ID / "data"
            style = (
                runtime
                / "bin"
                / "Qt6"
                / "plugins"
                / "styles"
                / "qgisplusstyle.dll"
            )
            style.parent.mkdir(parents=True)
            for path in (
                runtime / "bin" / "QGIS+.exe",
                runtime / "bin" / "qgis_process.exe",
                style,
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"test")

            license_path = root / "LICENSE"
            license_path.write_text("GPL test license", encoding="utf-8")
            install_script = root / "installscript.qs"
            install_script.write_text("function Component() {}", encoding="utf-8")

            prepare_ifw_package(
                runtime,
                output,
                "4.2.0",
                "2026-07-31",
                license_path,
                install_script,
            )

            config = ET.parse(output / "config" / "config.xml").getroot()
            package = ET.parse(
                output / "packages" / PACKAGE_ID / "meta" / "package.xml"
            ).getroot()
            self.assertEqual(config.findtext("Name"), "QGIS+")
            self.assertEqual(config.findtext("Version"), "4.2.0")
            self.assertEqual(
                config.findtext("TargetDir"), "@ApplicationsDirX64@/QGIS+"
            )
            self.assertEqual(package.findtext("Version"), "4.2.0")
            self.assertEqual(package.findtext("ReleaseDate"), "2026-07-31")
            self.assertEqual(package.findtext("ForcedInstallation"), "true")
            self.assertTrue(
                (
                    output
                    / "packages"
                    / PACKAGE_ID
                    / "meta"
                    / "installscript.qs"
                ).is_file()
            )


if __name__ == "__main__":
    unittest.main()

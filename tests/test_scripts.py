#!/usr/bin/env python3

from __future__ import annotations

import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from apply_qgis_patch import patch_cmake, patch_main, patch_windows_triplet
from prepare_ifw_package import PACKAGE_ID, prepare_ifw_package
from resolve_versions import (
    QGIS_RELEASE_RE,
    _qgis_version_from_build_tag,
    _select_release,
)


class WorkflowTests(unittest.TestCase):
    def test_remote_actions_use_full_commit_sha(self) -> None:
        workflows = Path(__file__).resolve().parents[1] / ".github/workflows"
        full_sha = re.compile(
            r"^[^/\s@]+/[^/\s@]+(?:/[^/\s@]+)*@[0-9a-f]{40}$"
        )

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
        windows_configure = (
            Path(__file__).resolve().parents[1]
            / "scripts/configure_windows_qgis.sh"
        ).read_text(encoding="utf-8")
        self.assertGreaterEqual(
            workflow.count("-D WITH_QSCIAPI=OFF")
            + windows_configure.count("-D WITH_QSCIAPI=OFF"),
            2,
        )
        self.assertIn("windows_dependencies:", workflow)
        self.assertIn("windows_build:", workflow)
        self.assertIn("windows_package:", workflow)
        self.assertIn("needs: [versions, windows_dependencies]", workflow)
        self.assertIn("needs: [versions, windows_build]", workflow)
        self.assertIn(
            "needs: [versions, windows_package, macos]", workflow
        )
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

    def test_windows_vcpkg_uses_runner_work_drive_and_resumable_cache(
        self,
    ) -> None:
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github/workflows/build.yml"
        ).read_text(encoding="utf-8")
        windows_jobs = workflow.split("  windows_dependencies:", 1)[1].split(
            "  windows_package:", 1
        )[0]
        windows_build = workflow.split("  windows_build:", 1)[1].split(
            "  windows_package:", 1
        )[0]

        self.assertIn(
            "$drive = Split-Path -Qualifier $env:RUNNER_TEMP",
            windows_jobs,
        )
        self.assertIn("shell: powershell", windows_jobs)
        self.assertIn(
            "iex (iwr -useb https://aka.ms/vcpkg-init.ps1)",
            windows_jobs,
        )
        self.assertIn('VCPKG_ROOT=$vcpkgRoot', windows_jobs)
        self.assertIn('VCPKG_BUILDTREES_ROOT=$buildtreesRoot', windows_jobs)
        self.assertIn(
            'X_VCPKG_REGISTRIES_CACHE=$registriesRoot',
            windows_jobs,
        )
        self.assertIn('VCPKG_DOWNLOADS=$downloadsRoot', windows_jobs)
        self.assertIn(
            '$registriesRoot = Join-Path $vcpkgRoot "registries"',
            windows_jobs,
        )
        self.assertIn(
            '$downloadsRoot = Join-Path $vcpkgRoot "downloads"',
            windows_jobs,
        )
        self.assertIn(
            'Join-Path $vcpkgRoot "vcpkg.exe"',
            windows_jobs,
        )
        self.assertIn(
            "VCPKG_BINARY_SOURCES: "
            "clear;files,D:/vcpkg-binary-cache,readwrite",
            windows_jobs,
        )
        self.assertGreaterEqual(
            windows_jobs.count("actions/cache/restore@cdf6c1fa"), 2
        )
        self.assertIn("actions/cache/save@cdf6c1fa", windows_jobs)
        self.assertIn("Warm QGIS dependencies", windows_jobs)
        self.assertIn("timeout-minutes: 330", windows_jobs)
        self.assertIn("Verify dependency cache is resumable", windows_jobs)
        self.assertEqual(
            windows_jobs.count(
                "Keep Python temporary files on the runner work drive"
            ),
            2,
        )
        self.assertEqual(windows_jobs.count('"TEMP=$tempRoot"'), 2)
        self.assertEqual(windows_jobs.count('"TMP=$tempRoot"'), 2)
        self.assertEqual(windows_jobs.count('"TMPDIR=$tempRoot"'), 2)
        self.assertEqual(windows_jobs.count("$workDrive -ne $tempDrive"), 2)
        self.assertIn("upstream/QGIS/vcpkg/vcpkg.json", windows_jobs)
        self.assertIn("needs: [versions, windows_dependencies]", windows_build)
        self.assertIn(
            "run: bash scripts/configure_windows_qgis.sh", windows_build
        )
        self.assertNotIn(
            "uses: ./upstream/QGIS/.github/actions/setup-vcpkg",
            windows_jobs,
        )
        self.assertNotIn("--x-buildtrees-root=C:/src", windows_jobs)
        self.assertNotIn("-D NUGET_TOKEN=", windows_jobs)
        self.assertNotIn(
            "Invoke-Expression $vcpkgInit.Content", windows_jobs
        )

        configure_script = (
            Path(__file__).resolve().parents[1]
            / "scripts/configure_windows_qgis.sh"
        ).read_text(encoding="utf-8")
        self.assertIn(
            '--x-buildtrees-root=${VCPKG_BUILDTREES_ROOT}',
            configure_script,
        )
        self.assertIn("-D ENABLE_UNITY_BUILDS=ON", configure_script)
        self.assertGreaterEqual(
            windows_jobs.count("continue-on-error: true"), 4
        )
        self.assertIn("Save completed Windows dependency cache", windows_build)
        self.assertIn(
            "the formal build will continue without the optimization",
            windows_jobs,
        )

    def test_macos_cache_is_owned_by_the_current_repository(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github/workflows/build.yml"
        ).read_text(encoding="utf-8")
        macos_job = workflow.split("  macos:", 1)[1].split(
            "  release:", 1
        )[0]

        self.assertIn("packages: write", workflow)
        self.assertIn(
            "https://nuget.pkg.github.com/"
            "${{ github.repository_owner }}/index.json",
            macos_job,
        )
        self.assertIn('-D NUGET_USERNAME="${GITHUB_ACTOR}"', macos_job)
        self.assertNotIn("nuget.pkg.github.com/qgis", macos_job)


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

    def test_release_build_tag_pins_exact_qgis_version(self) -> None:
        releases = [
            {
                "tag_name": "final-4_2_0",
                "draft": False,
                "prerelease": False,
            },
            {
                "tag_name": "final-4_2_1",
                "draft": False,
                "prerelease": False,
            },
        ]
        required_version = _qgis_version_from_build_tag("v4.2.0-r1")
        selected = _select_release(
            "qgis/QGIS",
            releases,
            QGIS_RELEASE_RE,
            required_major=4,
            required_version=required_version,
        )
        self.assertEqual(selected.tag, "final-4_2_0")

    def test_invalid_release_build_tag_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "must look like"):
            _qgis_version_from_build_tag("release-latest")


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
            triplet = root / "vcpkg/triplets/x64-windows-release.cmake"
            triplet.parent.mkdir(parents=True)
            triplet.write_text(
                "set(VCPKG_TARGET_ARCHITECTURE x64)\n"
                "set(VCPKG_CRT_LINKAGE dynamic)\n"
                "set(VCPKG_LIBRARY_LINKAGE dynamic)\n"
                "set(VCPKG_BUILD_TYPE release)\n",
                encoding="utf-8",
            )

            patch_main(root)
            patch_cmake(root)
            patch_windows_triplet(root)
            first_main = main.read_text(encoding="utf-8")
            first_cmake = cmake.read_text(encoding="utf-8")
            first_triplet = triplet.read_text(encoding="utf-8")
            patch_main(root)
            patch_cmake(root)
            patch_windows_triplet(root)
            self.assertEqual(first_main, main.read_text(encoding="utf-8"))
            self.assertEqual(first_cmake, cmake.read_text(encoding="utf-8"))
            self.assertEqual(
                first_triplet, triplet.read_text(encoding="utf-8")
            )
            self.assertIn("CMAKE_IGNORE_PREFIX_PATH", first_triplet)
            self.assertIn('PORT STREQUAL "vcpkg-gfortran"', first_triplet)
            self.assertIn("set(VCPKG_PROVIDED_FORTRAN ON)", first_triplet)
            self.assertIn(
                "C:/Program Files/Microsoft Visual Studio/*/*/VC/Tools/Llvm",
                first_triplet,
            )
            self.assertIn(
                '"${_qgisplus_llvm_prefix}/x64/bin"', first_triplet
            )

    def test_old_windows_triplet_patch_is_migrated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            triplet = root / "vcpkg/triplets/x64-windows-release.cmake"
            triplet.parent.mkdir(parents=True)
            triplet.write_text(
                "set(VCPKG_TARGET_ARCHITECTURE x64)\n\n"
                "# QGIS+ hosted-runner Fortran guard\n"
                'if(PORT STREQUAL "vcpkg-gfortran" OR '
                'PORT STREQUAL "lapack-reference")\n'
                "  list(APPEND CMAKE_IGNORE_PATH old/path)\n"
                "endif()\n",
                encoding="utf-8",
            )

            patch_windows_triplet(root)
            migrated = triplet.read_text(encoding="utf-8")
            self.assertIn("set(VCPKG_PROVIDED_FORTRAN ON)", migrated)
            patch_windows_triplet(root)
            self.assertEqual(migrated, triplet.read_text(encoding="utf-8"))


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

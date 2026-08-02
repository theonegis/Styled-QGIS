#!/usr/bin/env python3

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from apply_qgis_patch import (
    MACOS_DEPLOYMENT_TARGET,
    SIP_OVERLAY_MARKER,
    patch_cmake,
    patch_macos_triplets,
    patch_main,
    patch_sip_overlay_port,
    patch_windows_triplet,
)
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
        self.assertIn(
            "run: bash scripts/setup_macos_vcpkg.sh", macos_job
        )
        self.assertNotIn(
            "uses: ./upstream/QGIS/.github/actions/setup-vcpkg",
            macos_job,
        )

        setup_script = (
            Path(__file__).resolve().parents[1]
            / "scripts/setup_macos_vcpkg.sh"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'manifest["vcpkg-configuration"]'
            '["default-registry"]["baseline"]',
            setup_script,
        )
        self.assertIn('vcpkg_tool_version="2026-07-27"', setup_script)
        self.assertIn(
            'vcpkg_tool_sha256="352a52151f57e51b0298bdd6f6a825cd'
            '4413d3b88d258f456193daf783b3ceec"',
            setup_script,
        )
        self.assertIn("--retry 3 --retry-all-errors", setup_script)
        export_root = 'export VCPKG_ROOT="${vcpkg_root}"'
        standalone_bootstrap = (
            '"${vcpkg_executable}" bootstrap-standalone'
        )
        self.assertIn(export_root, setup_script)
        self.assertIn(standalone_bootstrap, setup_script)
        self.assertLess(
            setup_script.index(export_root),
            setup_script.index(standalone_bootstrap),
        )
        self.assertNotIn("bootstrap-vcpkg.sh", setup_script)

    def test_macos_dependency_configuration_is_resumable(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github/workflows/build.yml"
        ).read_text(encoding="utf-8")
        macos_job = workflow.split("  macos:", 1)[1].split(
            "  release:", 1
        )[0]

        self.assertIn("for attempt in 1 2", macos_job)
        self.assertIn("retrying from the resumable vcpkg state", macos_job)
        self.assertIn('rm -f "${QGIS_BUILD}/CMakeCache.txt"', macos_job)
        self.assertIn('rm -rf "${QGIS_BUILD}/CMakeFiles"', macos_job)

    def test_macos_requires_monterey_and_validates_dependency_patches(
        self,
    ) -> None:
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github/workflows/build.yml"
        ).read_text(encoding="utf-8")
        macos_job = workflow.split("  macos:", 1)[1].split(
            "  release:", 1
        )[0]

        self.assertIn(
            "- name: Intel\n"
            "            os: macos-15-intel\n"
            "            arch: x86_64\n"
            "            triplet: x64-osx-dynamic-release\n"
            '            deployment_target: "12.0"',
            macos_job,
        )
        self.assertEqual(macos_job.count('deployment_target: "12.0"'), 2)
        self.assertNotIn('deployment_target: "10.15"', macos_job)
        self.assertNotIn('deployment_target: "11.0"', macos_job)
        self.assertIn("Validate macOS dependency patches", macos_job)
        self.assertEqual(macos_job.count("-D CMAKE_BUILD_TYPE=Release"), 2)
        self.assertIn(
            "set(VCPKG_OSX_DEPLOYMENT_TARGET 12.0)", macos_job
        )
        self.assertIn(SIP_OVERLAY_MARKER, macos_job)
        self.assertIn('xcrun vtool -show-build "${binary}"', macos_job)
        self.assertIn('if [[ "${MIN_OS}" != "12.0" ]]', macos_job)
        self.assertIn('find "${APP_PATH}" -type f -print0', macos_job)
        self.assertIn('file -b "${binary}"', macos_job)
        self.assertIn('lipo -archs "${binary}"', macos_job)
        self.assertIn('Missing ${{ matrix.arch }} slice', macos_job)
        self.assertIn('otool -l "${binary}"', macos_job)
        self.assertIn('LC_VERSION_MIN_MACOSX', macos_job)
        self.assertIn("MIN_MAJOR > 12", macos_job)
        self.assertIn("macOS 12 incompatible binary", macos_job)
        self.assertIn("MACHO_COUNT == 0", macos_job)


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
    @staticmethod
    def _write_vcpkg_manifest(root: Path, baseline: str) -> None:
        vcpkg_dir = root / "vcpkg"
        vcpkg_dir.mkdir(parents=True, exist_ok=True)
        (vcpkg_dir / "vcpkg.json").write_text(
            json.dumps(
                {
                    "vcpkg-configuration": {
                        "registries": [
                            {
                                "kind": "git",
                                "baseline": baseline,
                                "repository": (
                                    "https://github.com/"
                                    "open-vcpkg/python-registry"
                                ),
                                "packages": ["py-*"],
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _write_macos_triplets(root: Path) -> tuple[Path, Path]:
        triplet_dir = root / "vcpkg/triplets"
        triplet_dir.mkdir(parents=True, exist_ok=True)
        intel = triplet_dir / "x64-osx-dynamic-release.cmake"
        arm = triplet_dir / "arm64-osx-dynamic-release.cmake"
        intel.write_text(
            "set(VCPKG_TARGET_ARCHITECTURE x64)\n"
            "set(VCPKG_OSX_DEPLOYMENT_TARGET 10.15)\n",
            encoding="utf-8",
        )
        arm.write_text(
            "set(VCPKG_TARGET_ARCHITECTURE arm64)\n"
            "set(VCPKG_OSX_DEPLOYMENT_TARGET 11.0)\n",
            encoding="utf-8",
        )
        return intel, arm

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

    def test_macos_triplets_and_sip_overlay_are_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            intel, arm = self._write_macos_triplets(root)
            self._write_vcpkg_manifest(
                root, "efa37f71edf9c676686040ffc4b7edaf2327e4d0"
            )

            patch_macos_triplets(root)
            patch_sip_overlay_port(root)
            first_intel = intel.read_text(encoding="utf-8")
            first_arm = arm.read_text(encoding="utf-8")
            portfile = root / "vcpkg/ports/py-sip/portfile.cmake"
            first_portfile = portfile.read_text(encoding="utf-8")

            patch_macos_triplets(root)
            patch_sip_overlay_port(root)
            self.assertEqual(first_intel, intel.read_text(encoding="utf-8"))
            self.assertEqual(first_arm, arm.read_text(encoding="utf-8"))
            self.assertEqual(
                first_portfile, portfile.read_text(encoding="utf-8")
            )
            self.assertIn(
                f"set(VCPKG_OSX_DEPLOYMENT_TARGET "
                f"{MACOS_DEPLOYMENT_TARGET})",
                first_intel,
            )
            self.assertIn(
                f"set(VCPKG_OSX_DEPLOYMENT_TARGET "
                f"{MACOS_DEPLOYMENT_TARGET})",
                first_arm,
            )
            self.assertIn(SIP_OVERLAY_MARKER, first_portfile)
            self.assertIn(
                'exec "$(dirname "$0")/../tools/python3/python3" '
                '-m @MODULE@ "$@"',
                first_portfile,
            )
            self.assertIn(
                'qgisplus_fixup_sip_entry_point('
                '"sip-distinfo" "sipbuild.tools.distinfo")',
                first_portfile,
            )

    def test_existing_upstream_sip_overlay_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            port_dir = root / "vcpkg/ports/py-sip"
            port_dir.mkdir(parents=True)
            portfile = port_dir / "portfile.cmake"
            portfile.write_text("upstream port\n", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "review it"):
                patch_sip_overlay_port(root)
            self.assertEqual(
                portfile.read_text(encoding="utf-8"), "upstream port\n"
            )

    def test_generated_sip_overlay_executes_with_cmake(self) -> None:
        cmake = shutil.which("cmake")
        if cmake is None:
            self.skipTest("CMake is not installed")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_vcpkg_manifest(
                root, "efa37f71edf9c676686040ffc4b7edaf2327e4d0"
            )
            patch_sip_overlay_port(root)
            package_dir = root / "package"
            portfile = root / "vcpkg/ports/py-sip/portfile.cmake"
            driver = root / "validate-sip-port.cmake"
            driver.write_text(
                f'''set(VERSION 6.15.3)
set(CURRENT_PACKAGES_DIR "{package_dir.as_posix()}")
set(SOURCE_PATH "{(root / "source").as_posix()}")
set(python_versioned python3.12)
set(VCPKG_TARGET_IS_WINDOWS FALSE)

function(vcpkg_from_pythonhosted)
  set(SOURCE_PATH "{(root / "source").as_posix()}" PARENT_SCOPE)
endfunction()

function(vcpkg_python_build_and_install_wheel)
  file(MAKE_DIRECTORY "${{CURRENT_PACKAGES_DIR}}/bin")
  foreach(script sip-build sip-distinfo sip-install sip-module sip-sdist sip-wheel)
    file(WRITE "${{CURRENT_PACKAGES_DIR}}/bin/${{script}}" "#!/bin/sh\\n")
  endforeach()
endfunction()

function(vcpkg_install_copyright)
endfunction()

function(vcpkg_fixup_shebang)
  message(FATAL_ERROR "Windows helper must not run on macOS")
endfunction()

include("{portfile.as_posix()}")
''',
                encoding="utf-8",
            )

            result = subprocess.run(
                [cmake, "-P", str(driver)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                result.returncode,
                0,
                msg=f"{result.stdout}\n{result.stderr}",
            )
            wrapper = (package_dir / "bin/sip-distinfo").read_text(
                encoding="utf-8"
            )
            self.assertEqual(
                wrapper,
                '#!/bin/sh\n'
                'exec "$(dirname "$0")/../tools/python3/python3" '
                '-m sipbuild.tools.distinfo "$@"\n',
            )

    def test_changed_python_registry_requires_overlay_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_vcpkg_manifest(root, "0" * 40)

            with self.assertRaisesRegex(RuntimeError, "Python registry changed"):
                patch_sip_overlay_port(root)
            self.assertFalse((root / "vcpkg/ports/py-sip").exists())

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

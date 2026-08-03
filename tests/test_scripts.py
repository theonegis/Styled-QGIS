#!/usr/bin/env python3

from __future__ import annotations

import json
import os
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
    PYTHON_RUNTIME_OVERLAY_MARKER,
    SIP_OVERLAY_MARKER,
    patch_cmake,
    patch_macos_triplets,
    patch_main,
    patch_python_runtime_overlays,
    patch_sip_overlay_port,
    patch_windows_triplet,
)
from audit_python_runtime_dependencies import audit
from prepare_ifw_package import PACKAGE_ID, prepare_ifw_package
from prepare_vcpkg_shard import (
    SHARDS,
    create_shard_manifest,
    dependency_shard,
)
from resolve_versions import (
    QGIS_RELEASE_RE,
    _qgis_version_from_build_tag,
    _select_release,
)


class VcpkgShardTests(unittest.TestCase):
    def test_all_dependency_categories_are_stable(self) -> None:
        self.assertEqual(dependency_shard("qtdeclarative"), "qt")
        self.assertEqual(dependency_shard("py-pyqt6"), "qt")
        self.assertEqual(dependency_shard("gdal"), "geo")
        self.assertEqual(dependency_shard("py-duckdb"), "geo")
        self.assertEqual(dependency_shard("py-beautifulsoup4"), "geo")
        self.assertEqual(dependency_shard("py-numpy"), "python")
        self.assertEqual(dependency_shard("protobuf"), "base")

    def test_libpysal_import_dependency_stays_in_geo_shard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "vcpkg.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "vcpkg-configuration": {},
                        "dependencies": [
                            "py-pysal",
                            "py-beautifulsoup4",
                            "py-numpy",
                            "protobuf",
                        ],
                    }
                ),
                encoding="utf-8",
            )

            geo = create_shard_manifest(manifest_path, "geo", [])
            python = create_shard_manifest(manifest_path, "python", [])

            self.assertEqual(
                geo["dependencies"],
                ["py-pysal", "py-beautifulsoup4"],
            )
            self.assertEqual(python["dependencies"], ["py-numpy"])

    def test_vcpkg_shard_installer_retries_with_existing_state(self) -> None:
        root = Path(__file__).resolve().parents[1]
        installer = root / "scripts/install_vcpkg_shard.sh"

        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            attempts = temp / "attempts.txt"
            command = temp / "eventually-succeeds.sh"
            command.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                'count="$(wc -l < "$1" 2>/dev/null || true)"\n'
                'printf "attempt\\n" >> "$1"\n'
                '(( count >= 2 ))\n',
                encoding="utf-8",
            )
            command.chmod(0o755)
            env = os.environ.copy()
            env["VCPKG_INSTALL_RETRY_DELAY_SECONDS"] = "0"
            result = subprocess.run(
                ["bash", str(installer), str(command), str(attempts)],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                attempts.read_text(encoding="utf-8").splitlines(),
                ["attempt", "attempt", "attempt"],
            )
            self.assertEqual(result.stdout.count("::warning::"), 2)

    def test_vcpkg_shard_installer_falls_back_from_restored_cache(self) -> None:
        root = Path(__file__).resolve().parents[1]
        installer = root / "scripts/install_vcpkg_shard.sh"

        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            restored = temp / "restored"
            writable = temp / "writable"
            install_root = temp / "installed"
            buildtrees = temp / "buildtrees"
            for path in (restored, writable, install_root, buildtrees):
                path.mkdir()
            (restored / "bad.zip").write_text("broken", encoding="utf-8")
            (install_root / "stale.txt").write_text("stale", encoding="utf-8")
            (buildtrees / "stale.txt").write_text("stale", encoding="utf-8")

            command = temp / "cache-aware-command.sh"
            command.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                'if [[ "$VCPKG_BINARY_SOURCES" == *restored* ]]; then\n'
                "  exit 27\n"
                "fi\n"
                '[[ ! -e "$VCPKG_INSTALL_ROOT_TO_RESET/stale.txt" ]]\n'
                '[[ ! -e "$VCPKG_BUILDTREES_ROOT_TO_RESET/stale.txt" ]]\n'
                'printf "good" > "$VCPKG_WRITABLE_BINARY_CACHE/good.zip"\n',
                encoding="utf-8",
            )
            command.chmod(0o755)
            env = os.environ.copy()
            env.update(
                {
                    "VCPKG_INSTALL_RETRY_DELAY_SECONDS": "0",
                    "VCPKG_BINARY_SOURCES": (
                        f"clear;files,{restored},read;"
                        f"files,{writable},readwrite"
                    ),
                    "VCPKG_RESTORED_BINARY_CACHE": str(restored),
                    "VCPKG_WRITABLE_BINARY_CACHE": str(writable),
                    "VCPKG_INSTALL_ROOT_TO_RESET": str(install_root),
                    "VCPKG_BUILDTREES_ROOT_TO_RESET": str(buildtrees),
                }
            )
            result = subprocess.run(
                ["bash", str(installer), str(command)],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((writable / "good.zip").is_file())
            self.assertFalse((writable / "bad.zip").exists())
            self.assertIn("disabled it", result.stdout)

    def test_successful_restored_cache_is_merged_without_overwrite(self) -> None:
        root = Path(__file__).resolve().parents[1]
        installer = root / "scripts/install_vcpkg_shard.sh"

        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            restored = temp / "restored"
            writable = temp / "writable"
            restored.mkdir()
            writable.mkdir()
            (restored / "only-restored.zip").write_text("cached", encoding="utf-8")
            (restored / "newer.zip").write_text("old", encoding="utf-8")
            (writable / "newer.zip").write_text("new", encoding="utf-8")

            env = os.environ.copy()
            env.update(
                {
                    "VCPKG_RESTORED_BINARY_CACHE": str(restored),
                    "VCPKG_WRITABLE_BINARY_CACHE": str(writable),
                }
            )
            result = subprocess.run(
                ["bash", str(installer), "/usr/bin/true"],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                (writable / "only-restored.zip").read_text(encoding="utf-8"),
                "cached",
            )
            self.assertEqual(
                (writable / "newer.zip").read_text(encoding="utf-8"),
                "new",
            )

    def test_python_runtime_audit_detects_missing_dependency_edges(self) -> None:
        ports = {
            "py-parent": {
                "distribution": "parent",
                "manifest": {"dependencies": []},
            },
            "py-child": {
                "distribution": "child",
                "manifest": {"dependencies": []},
            },
        }
        metadata = {
            "parent": {"requires_dist": ["child>=1"]},
            "child": {"requires_dist": []},
        }
        self.assertEqual(
            audit(ports, {"py-parent", "py-child"}, metadata),
            ["py-parent: missing runtime dependency py-child (child>=1)"],
        )
        ports["py-parent"]["manifest"]["dependencies"] = ["py-child"]
        self.assertEqual(
            audit(ports, {"py-parent", "py-child"}, metadata), []
        )

    def test_offline_verifier_blocks_downloads_and_source_builds(self) -> None:
        root = Path(__file__).resolve().parents[1]
        verifier = root / "scripts/verify_offline_vcpkg.py"
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            manifest = temp / "vcpkg.json"
            manifest.write_text(
                json.dumps(
                    {
                        "vcpkg-configuration": {
                            "default-registry": {
                                "kind": "git",
                                "baseline": "a" * 40,
                                "repository": "https://example.test/vcpkg",
                            }
                        },
                        "dependencies": [
                            "protobuf",
                            "gdal",
                            "py-numpy",
                            "qtbase",
                        ],
                    }
                ),
                encoding="utf-8",
            )
            cache = temp / "binary-cache"
            registries = temp / "registries"
            cache.mkdir()
            registries.mkdir()
            log = temp / "vcpkg.log"
            fake_vcpkg = temp / "vcpkg"
            fake_vcpkg.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                'printf "%s|%s|%s\\n" '
                '"$VCPKG_BINARY_SOURCES" "$X_VCPKG_ASSET_SOURCES" "$*" '
                '>> "$VCPKG_TEST_LOG"\n',
                encoding="utf-8",
            )
            fake_vcpkg.chmod(0o755)
            env = os.environ.copy()
            env["VCPKG_TEST_LOG"] = str(log)
            result = subprocess.run(
                [
                    sys.executable,
                    str(verifier),
                    "--vcpkg",
                    str(fake_vcpkg),
                    "--manifest",
                    str(manifest),
                    "--triplet",
                    "test-triplet",
                    "--binary-cache",
                    str(cache),
                    "--registries-cache",
                    str(registries),
                    "--work-dir",
                    str(temp / "verify"),
                ],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = log.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 4)
            for line in lines:
                self.assertIn("clear;files,", line)
                self.assertIn("clear;x-block-origin", line)
                self.assertIn("--only-binarycaching", line)
                self.assertIn("--no-downloads", line)

    def test_manifest_features_are_partitioned_without_losing_duplicates(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "vcpkg.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "vcpkg-configuration": {
                            "default-registry": {
                                "kind": "git",
                                "baseline": "a" * 40,
                                "repository": "https://example.test/vcpkg",
                            },
                            "overlay-ports": ["ports"],
                            "overlay-triplets": ["triplets"],
                        },
                        "name": "qgis",
                        "version-string": "current",
                        "dependencies": [
                            {
                                "name": "gdal",
                                "default-features": False,
                                "features": ["zstd"],
                            },
                            "qtbase",
                            "protobuf",
                        ],
                        "features": {
                            "recommended-features": {
                                "dependencies": [
                                    {
                                        "name": "gdal",
                                        "features": ["parquet"],
                                    },
                                    "qtdeclarative",
                                ]
                            },
                            "bindings": {
                                "dependencies": [
                                    {
                                        "name": "gdal",
                                        "features": ["python"],
                                    },
                                    "py-numpy",
                                    "py-pyqt6",
                                ]
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            features = ["recommended-features", "bindings"]
            manifests = {
                shard: create_shard_manifest(
                    manifest_path, shard, features
                )
                for shard in SHARDS
            }

            all_dependencies = [
                item
                for manifest in manifests.values()
                for item in manifest["dependencies"]
            ]
            self.assertEqual(len(all_dependencies), 8)
            geo_dependencies = manifests["geo"]["dependencies"]
            self.assertEqual(
                [item["name"] for item in geo_dependencies],
                ["gdal", "gdal", "gdal"],
            )
            self.assertEqual(
                manifests["qt"]["dependencies"],
                ["qtbase", "qtdeclarative", "py-pyqt6"],
            )
            self.assertEqual(
                manifests["python"]["dependencies"], ["py-numpy"]
            )
            self.assertEqual(
                manifests["base"]["dependencies"], ["protobuf"]
            )
            for manifest in manifests.values():
                config = manifest["vcpkg-configuration"]
                self.assertEqual(
                    config["overlay-ports"],
                    [str((root / "ports").resolve())],
                )
                self.assertEqual(
                    config["overlay-triplets"],
                    [str((root / "triplets").resolve())],
                )

    def test_unknown_feature_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "vcpkg.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "vcpkg-configuration": {},
                        "dependencies": ["zlib"],
                        "features": {},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "Unknown vcpkg"):
                create_shard_manifest(
                    manifest_path, "base", ["does-not-exist"]
                )


class WorkflowTests(unittest.TestCase):
    def test_critical_build_failures_cancel_all_platform_jobs(self) -> None:
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/build.yml").read_text(
            encoding="utf-8"
        )
        cancellation_script = (
            root / "scripts/cancel_workflow.sh"
        ).read_text(encoding="utf-8")

        self.assertIn("actions: write", workflow)
        self.assertNotIn("fail-fast: false", workflow)
        self.assertEqual(workflow.count("fail-fast: true"), 3)
        self.assertGreaterEqual(
            workflow.count("run: bash scripts/cancel_workflow.sh"), 5
        )
        self.assertIn("failure() && !cancelled()", workflow)
        self.assertIn(
            'actions/runs/${GITHUB_RUN_ID}/cancel', cancellation_script
        )

    def test_platform_configure_scripts_enforce_offline_inputs(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for script_name in (
            "configure_macos_qgis.sh",
            "configure_windows_qgis.sh",
        ):
            script = (root / "scripts" / script_name).read_text(
                encoding="utf-8"
            )
            self.assertIn('QGISPLUS_OFFLINE:-0', script)
            self.assertIn("VCPKG_BINARY_SOURCES", script)
            self.assertIn("X_VCPKG_ASSET_SOURCES", script)
            self.assertIn("X_VCPKG_REGISTRIES_CACHE", script)
            self.assertIn("x-block-origin", script)
            self.assertIn("--only-binarycaching", script)
            self.assertIn("--no-downloads", script)

    def test_platform_builds_disable_3d_and_point_cloud_dependencies(self) -> None:
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/build.yml").read_text(
            encoding="utf-8"
        )
        for script_name in (
            "configure_macos_qgis.sh",
            "configure_windows_qgis.sh",
        ):
            script = (root / "scripts" / script_name).read_text(
                encoding="utf-8"
            )
            self.assertIn("-D WITH_3D=OFF", script)
            self.assertIn("-D WITH_PDAL=OFF", script)
        self.assertNotIn("--feature 3d", workflow)
        self.assertNotIn("--feature pdal", workflow)

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
        macos_configure = (
            Path(__file__).resolve().parents[1]
            / "scripts/configure_macos_qgis.sh"
        ).read_text(encoding="utf-8")
        self.assertGreaterEqual(
            workflow.count("-D WITH_QSCIAPI=OFF")
            + windows_configure.count("-D WITH_QSCIAPI=OFF")
            + macos_configure.count("-D WITH_QSCIAPI=OFF"),
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

    def test_windows_vcpkg_uses_fresh_parallel_run_local_shards(
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
        self.assertNotIn("actions/cache/", windows_jobs)
        self.assertIn("shard: [base, geo, python, qt]", windows_jobs)
        self.assertIn("Build dependency shard from source", windows_jobs)
        self.assertIn("prepare_vcpkg_shard.py", windows_jobs)
        self.assertIn("install_vcpkg_shard.sh", windows_jobs)
        self.assertIn(
            "Restore partial Windows shard from a previous attempt",
            windows_jobs,
        )
        self.assertIn(
            "Preserve partial Windows dependency archives",
            windows_jobs,
        )
        self.assertIn("github.run_attempt > 1", windows_jobs)
        self.assertIn("QGISPlus-partial-vcpkg-", windows_jobs)
        self.assertIn("merge-multiple: true", windows_jobs)
        self.assertIn("D:/vcpkg-restored-binary-cache,read", windows_jobs)
        self.assertIn("D:/vcpkg-binary-cache,readwrite", windows_jobs)
        self.assertIn("VCPKG_INSTALL_ROOT_TO_RESET", windows_jobs)
        self.assertIn(
            'VCPKG_BUILDTREES_ROOT_TO_RESET="${VCPKG_BUILDTREES_ROOT}"',
            windows_jobs,
        )
        self.assertIn("--x-manifest-root=", windows_jobs)
        self.assertIn("--x-install-root=", windows_jobs)
        self.assertIn(
            "Upload run-local Windows dependency archives", windows_jobs
        )
        self.assertIn(
            "Download this run's Windows dependency archives", windows_jobs
        )
        self.assertIn("${{ github.run_id }}-${{ matrix.shard }}", windows_jobs)
        self.assertIn("Expected four dependency shards", windows_build)
        self.assertIn("files,$path,read", windows_build)
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
        self.assertIn('${QGIS_SOURCE}/vcpkg/vcpkg.json', windows_jobs)
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
        dependency_build_step = windows_jobs.split(
            "- name: Build dependency shard from source", 1
        )[1].split(
            "- name: Upload run-local Windows dependency archives", 1
        )[0]
        self.assertNotIn("continue-on-error: true", dependency_build_step)
        self.assertNotIn("Save completed Windows dependency cache", windows_build)

    def test_macos_vcpkg_uses_fresh_run_local_shards(self) -> None:
        root = Path(__file__).resolve().parents[1]
        workflow = (
            root / ".github/workflows/build.yml"
        ).read_text(encoding="utf-8")
        macos_job = workflow.split("  macos:", 1)[1].split(
            "  release:", 1
        )[0]
        macos_jobs = workflow.split("  macos_dependencies:", 1)[1].split(
            "  release:", 1
        )[0]
        configure_script = (
            root / "scripts/configure_macos_qgis.sh"
        ).read_text(encoding="utf-8")

        self.assertNotIn("packages: write", workflow)
        self.assertNotIn("nuget.pkg.github.com", macos_jobs)
        self.assertNotIn("NUGET_", configure_script)
        self.assertIn("prepare_vcpkg_shard.py", macos_jobs)
        self.assertIn("install_vcpkg_shard.sh", macos_jobs)
        self.assertIn(
            "Restore partial macOS shard from a previous attempt",
            macos_jobs,
        )
        self.assertIn(
            "Preserve partial macOS dependency archives",
            macos_jobs,
        )
        self.assertIn("github.run_attempt > 1", macos_jobs)
        self.assertIn("QGISPlus-partial-vcpkg-", macos_jobs)
        self.assertIn("merge-multiple: true", macos_jobs)
        self.assertIn("vcpkg-restored-binary-cache,read", macos_jobs)
        self.assertIn("vcpkg-binary-cache,readwrite", macos_jobs)
        self.assertIn("VCPKG_INSTALL_ROOT_TO_RESET", macos_jobs)
        self.assertEqual(
            macos_jobs.count("Build dependency shard from source"), 1
        )
        self.assertEqual(
            macos_jobs.count("Upload run-local macOS dependency archives"),
            1,
        )
        self.assertIn(
            "Download this run's macOS dependency archives", macos_job
        )
        self.assertIn("Expected four dependency shards", macos_job)
        self.assertIn("${{ github.run_id", macos_jobs)
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

    def test_macos_dependency_configuration_uses_only_current_run(
        self,
    ) -> None:
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github/workflows/build.yml"
        ).read_text(encoding="utf-8")
        dependency_job = workflow.split(
            "  macos_dependencies:", 1
        )[1].split("  macos:", 1)[0]
        macos_job = workflow.split("  macos:", 1)[1].split(
            "  release:", 1
        )[0]

        self.assertIn("needs: [versions, macos_dependencies]", macos_job)
        dependency_build_step = dependency_job.split(
            "- name: Build dependency shard from source", 1
        )[1].split(
            "- name: Upload run-local macOS dependency archives", 1
        )[0]
        self.assertNotIn("continue-on-error: true", dependency_build_step)
        self.assertNotIn("NUGET_", dependency_job)
        self.assertNotIn("actions/cache/", dependency_job)
        self.assertIn("retention-days: 1", dependency_job)
        self.assertIn("compression-level: 0", dependency_job)
        self.assertIn("for attempt in 1 2", macos_job)
        self.assertIn("retrying from the resumable vcpkg state", macos_job)
        self.assertIn('rm -f "${QGIS_BUILD}/CMakeCache.txt"', macos_job)
        self.assertIn('rm -rf "${QGIS_BUILD}/CMakeFiles"', macos_job)

    def test_macos_requires_monterey_and_validates_dependency_patches(
        self,
    ) -> None:
        root = Path(__file__).resolve().parents[1]
        workflow = (
            root / ".github/workflows/build.yml"
        ).read_text(encoding="utf-8")
        macos_job = workflow.split("  macos:", 1)[1].split(
            "  release:", 1
        )[0]
        configure_script = (
            root / "scripts/configure_macos_qgis.sh"
        ).read_text(encoding="utf-8")
        verification_script = (
            root / "scripts/verify_macos_bundle.sh"
        ).read_text(encoding="utf-8")

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
        self.assertIn("-D CMAKE_BUILD_TYPE=Release", configure_script)
        self.assertIn("-D CMAKE_BUILD_TYPE=Release", macos_job)
        self.assertIn(
            'export MACOSX_DEPLOYMENT_TARGET=', configure_script
        )
        self.assertIn("-D WITH_ORACLE=OFF", configure_script)
        self.assertNotIn("--feature oracle", workflow)
        self.assertIn(
            "MACOSX_DEPLOYMENT_TARGET: ${{ matrix.deployment_target }}",
            macos_job,
        )
        self.assertIn(
            "set(VCPKG_OSX_DEPLOYMENT_TARGET 12.0)", macos_job
        )
        self.assertIn(SIP_OVERLAY_MARKER, macos_job)
        self.assertIn(
            "bash scripts/verify_macos_bundle.sh", macos_job
        )
        self.assertIn("Upload macOS verification diagnostics", macos_job)
        self.assertIn("if: always()", macos_job)
        self.assertIn(
            'xcrun vtool -show-build "${binary}"', verification_script
        )
        self.assertIn(
            'find "${app_path}" -type f -print0', verification_script
        )
        self.assertIn('file -b "${binary}"', verification_script)
        self.assertIn('lipo -archs "${binary}"', verification_script)
        self.assertIn('otool -l "${binary}"', verification_script)
        self.assertIn("LC_VERSION_MIN_MACOSX", verification_script)
        self.assertIn("min_major > max_major", verification_script)
        self.assertIn("macho_count == 0", verification_script)
        self.assertNotIn("deployment_command = (\n", verification_script)

        syntax_check = subprocess.run(
            ["bash", "-n", str(root / "scripts/verify_macos_bundle.sh")],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(syntax_check.returncode, 0, syntax_check.stderr)

    def test_macos_bundle_verifier_accepts_a_valid_bundle(self) -> None:
        root = Path(__file__).resolve().parents[1]
        verifier = root / "scripts/verify_macos_bundle.sh"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            app = temp / "QGIS+.app"
            main_binary = app / "Contents/MacOS/QGIS+"
            style_plugin = (
                app / "Contents/PlugIns/styles/libqgisplusstyle.dylib"
            )
            tools = temp / "bin"
            main_binary.parent.mkdir(parents=True)
            style_plugin.parent.mkdir(parents=True)
            tools.mkdir()

            main_binary.write_text(
                "#!/usr/bin/env bash\necho 'QGIS 4.2.1'\n",
                encoding="utf-8",
            )
            main_binary.chmod(0o755)
            style_plugin.write_text("plugin", encoding="utf-8")

            mock_tools = {
                "file": "#!/usr/bin/env bash\necho 'Mach-O 64-bit'\n",
                "lipo": "#!/usr/bin/env bash\necho 'arm64'\n",
                "xcrun": (
                    "#!/usr/bin/env bash\n"
                    "printf '      minos 12.0\\n'\n"
                ),
                "otool": (
                    "#!/usr/bin/env bash\n"
                    "cat <<'EOF'\n"
                    "Load command 1\n"
                    "      cmd LC_BUILD_VERSION\n"
                    "  cmdsize 32\n"
                    " platform 1\n"
                    "    minos 12.0\n"
                    "      sdk 15.0\n"
                    "EOF\n"
                ),
            }
            for name, content in mock_tools.items():
                path = tools / name
                path.write_text(content, encoding="utf-8")
                path.chmod(0o755)

            env = os.environ.copy()
            env["PATH"] = f"{tools}{os.pathsep}{env['PATH']}"
            result = subprocess.run(
                ["bash", str(verifier), str(app), "arm64", "12.0"],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Inspected 2 Mach-O files", result.stdout)
        self.assertIn("macOS bundle verification passed", result.stdout)


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

    def test_macos_and_python_overlays_are_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            intel, arm = self._write_macos_triplets(root)
            self._write_vcpkg_manifest(
                root, "efa37f71edf9c676686040ffc4b7edaf2327e4d0"
            )

            patch_macos_triplets(root)
            patch_sip_overlay_port(root)
            patch_python_runtime_overlays(root)
            first_intel = intel.read_text(encoding="utf-8")
            first_arm = arm.read_text(encoding="utf-8")
            portfile = root / "vcpkg/ports/py-sip/portfile.cmake"
            first_portfile = portfile.read_text(encoding="utf-8")

            patch_macos_triplets(root)
            patch_sip_overlay_port(root)
            patch_python_runtime_overlays(root)
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

            referencing_port = root / "vcpkg/ports/py-referencing"
            referencing_portfile = (
                referencing_port / "portfile.cmake"
            ).read_text(encoding="utf-8")
            referencing_manifest = json.loads(
                (referencing_port / "vcpkg.json").read_text(encoding="utf-8")
            )
            self.assertIn(PYTHON_RUNTIME_OVERLAY_MARKER, referencing_portfile)
            self.assertIn(
                "py-typing-extensions",
                referencing_manifest["dependencies"],
            )

            libpysal_port = root / "vcpkg/ports/py-libpysal"
            libpysal_manifest = json.loads(
                (libpysal_port / "vcpkg.json").read_text(encoding="utf-8")
            )
            self.assertIn(
                "py-beautifulsoup4",
                libpysal_manifest["dependencies"],
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

            with self.assertRaisesRegex(RuntimeError, "Python registry changed"):
                patch_python_runtime_overlays(root)
            self.assertFalse(
                (root / "vcpkg/ports/py-referencing").exists()
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

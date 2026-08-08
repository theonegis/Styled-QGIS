from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


binary_packages = load_script("resolve_binary_packages.py")
package_matrix = load_script("resolve_package_matrix.py")
release_versions = load_script("resolve_versions.py")
release_tags = load_script("resolve_release_tag.py")
verified_download = load_script("download_verified.py")
windows_stage = load_script("stage_windows_binary.py")
ifw = load_script("prepare_ifw_package.py")


class BinaryPackageTests(unittest.TestCase):
    def test_qgis_4_2_1_uses_official_installer_names(self) -> None:
        packages = binary_packages.resolve_packages("4.2.1")
        self.assertEqual(packages["windows"]["name"], "QGIS-OSGeo4W-4.2.1-1.msi")
        self.assertEqual(packages["macos"]["name"], "qgis_pr_final-4_2_1.dmg")
        self.assertTrue(packages["windows"]["url"].startswith("https://download.qgis.org/"))
        self.assertTrue(packages["macos"]["checksum_url"].endswith(".sha256sum"))

    def test_invalid_version_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            binary_packages.resolve_packages("4.2")


class ReleaseVersionTests(unittest.TestCase):
    def test_qgis_selection_uses_semver_instead_of_publish_time(self) -> None:
        releases = [
            {
                "tag_name": "final-4_1_9",
                "published_at": "2026-08-02T00:00:00Z",
                "draft": False,
                "prerelease": False,
            },
            {
                "tag_name": "final-4_2_1",
                "published_at": "2026-08-01T00:00:00Z",
                "draft": False,
                "prerelease": False,
            },
        ]
        selected = release_versions._select_release(
            "qgis/QGIS", releases, release_versions.QGIS_RELEASE_RE, required_major=4
        )
        self.assertEqual(selected.version, "4.2.1")

    def test_release_revision_pins_qgis_version(self) -> None:
        self.assertEqual(
            release_versions._qgis_version_from_build_tag("v4.2.1-r16"),
            (4, 2, 1),
        )

    def test_automatic_release_tag_increments_current_qgis_revision(self) -> None:
        self.assertEqual(
            release_tags.next_release_tag(
                "4.2.1", ["v4.2.1-r14", "v4.2.1-r15", "v4.2.0-r20"]
            ),
            "v4.2.1-r16",
        )

    def test_requested_release_tag_must_match_qgis_version(self) -> None:
        self.assertEqual(
            release_tags.next_release_tag("4.2.1", [], "v4.2.1-r20"),
            "v4.2.1-r20",
        )
        with self.assertRaises(ValueError):
            release_tags.next_release_tag("4.2.1", [], "v4.2.0-r20")


class MatrixTests(unittest.TestCase):
    def test_non_dispatch_builds_all_platforms(self) -> None:
        matrix = package_matrix.resolve_matrix("schedule", "false", "false", "false")
        self.assertEqual(len(matrix["include"]), 3)
        windows = next(
            platform for platform in matrix["include"]
            if platform["platform"] == "windows"
        )
        self.assertEqual(windows["os"], "windows-2022")

    def test_dispatch_can_select_one_platform(self) -> None:
        matrix = package_matrix.resolve_matrix(
            "workflow_dispatch", "false", "true", "false"
        )
        self.assertEqual(matrix["include"][0]["platform"], "macos-intel")

    def test_empty_dispatch_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            package_matrix.resolve_matrix(
                "workflow_dispatch", "false", "false", "false"
            )


class VerifiedDownloadTests(unittest.TestCase):
    def test_download_is_checksum_verified_and_reused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.bin"
            source.write_bytes(b"official-qgis-package")
            checksum = hashlib.sha256(source.read_bytes()).hexdigest()
            checksum_file = root / "source.sha256sum"
            checksum_file.write_text(f"{checksum}  source.bin\n", encoding="utf-8")
            destination = root / "cache" / "package.bin"
            reused = verified_download.ensure_verified(
                source.as_uri(), checksum_file.as_uri(), destination, retries=1
            )
            self.assertFalse(reused)
            self.assertEqual(destination.read_bytes(), source.read_bytes())
            self.assertTrue(
                verified_download.ensure_verified(
                    source.as_uri(), checksum_file.as_uri(), destination, retries=1
                )
            )

    def test_bad_checksum_removes_download(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.bin"
            source.write_bytes(b"content")
            checksum_file = root / "source.sha256sum"
            checksum_file.write_text("0" * 64, encoding="utf-8")
            destination = root / "package.bin"
            with self.assertRaises(RuntimeError):
                verified_download.ensure_verified(
                    source.as_uri(), checksum_file.as_uri(), destination, retries=1
                )
            self.assertFalse(destination.exists())


class WindowsStagingTests(unittest.TestCase):
    def test_theme_and_registrar_are_added_to_each_qgis_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            (runtime / "bin").mkdir(parents=True)
            (runtime / "bin" / "qgis.bat").write_text("@echo off\n")
            for theme_root in (
                runtime / "apps" / "qgis" / "resources" / "themes",
                runtime / "share" / "qgis" / "resources" / "themes",
            ):
                default_theme = theme_root / "default"
                default_theme.mkdir(parents=True)
                (default_theme / "style.qss").write_text("/* default */\n")
            for plugin_root in (
                runtime / "apps" / "qgis" / "python" / "plugins",
                runtime / "share" / "qgis" / "python" / "plugins",
            ):
                (plugin_root / "processing").mkdir(parents=True)
            launcher = root / "QGIS+.exe"
            launcher.write_bytes(b"launcher")
            theme = root / "QGISPlus Material"
            theme.mkdir()
            for name in ("style.qss", "variables.qss", "palette.txt"):
                (theme / name).write_text(f"/* {name} */\n", encoding="utf-8")
            theme_plugin = root / "qgisplus_theme"
            theme_plugin.mkdir()
            for name in ("__init__.py", "plugin.py", "metadata.txt"):
                (theme_plugin / name).write_text(
                    f"# {name}\n", encoding="utf-8"
                )
            settings = root / "qgisplus-global-settings.ini"
            settings.write_text(
                "[qgis]\nstyle=Fusion\n[UI]\nUITheme=QGISPlus Material\n"
                "[PythonPlugins]\nqgisplus_theme=true\n",
                encoding="utf-8",
            )
            installed_themes, installed_plugins = windows_stage.stage(
                runtime, launcher, theme, theme_plugin, settings
            )
            self.assertEqual(len(installed_themes), 2)
            self.assertEqual(len(installed_plugins), 2)
            self.assertTrue((runtime / "QGIS+.exe").is_file())
            self.assertEqual(
                (runtime / "qgisplus-launcher.txt").read_text(), "bin/qgis.bat"
            )
            self.assertEqual(
                (runtime / "qgisplus-global-settings.ini").read_text(),
                "[qgis]\nstyle=Fusion\n[UI]\nUITheme=QGISPlus Material\n"
                "[PythonPlugins]\nqgisplus_theme=true\n",
            )
            self.assertTrue(
                all((path / "style.qss").is_file() for path in installed_themes)
            )
            self.assertTrue(
                all((path / "metadata.txt").is_file() for path in installed_plugins)
            )


class QtIfwTests(unittest.TestCase):
    def test_metadata_wraps_extracted_official_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "ifw"
            runtime = output / "packages" / ifw.PACKAGE_ID / "data"
            (runtime / "bin").mkdir(parents=True)
            (runtime / "QGIS+.exe").write_bytes(b"launcher")
            (runtime / "qgisplus-launcher.txt").write_text(
                "bin/qgis.bat", encoding="utf-8"
            )
            (runtime / "qgisplus-global-settings.ini").write_text(
                "[qgis]\nstyle=Fusion\n[UI]\nUITheme=QGISPlus Material\n"
                "[PythonPlugins]\nqgisplus_theme=true\n",
                encoding="utf-8",
            )
            (runtime / "bin" / "qgis.bat").write_text("@echo off\n")
            material = (
                runtime
                / "apps"
                / "qgis"
                / "resources"
                / "themes"
                / "QGISPlus Material"
            )
            material.mkdir(parents=True)
            (material / "style.qss").write_text("/* QGISPlus Material */\n")
            registrar = (
                runtime
                / "apps"
                / "qgis"
                / "python"
                / "plugins"
                / "qgisplus_theme"
            )
            registrar.mkdir(parents=True)
            (registrar / "metadata.txt").write_text(
                "[general]\nname=QGISPlus Material Theme\n",
                encoding="utf-8",
            )
            license_path = root / "LICENSE"
            license_path.write_text("GPL", encoding="utf-8")
            install_script = root / "installscript.qs"
            install_script.write_text("function Component() {}", encoding="utf-8")
            ifw.prepare_ifw_package(
                runtime, output, "4.2.1", "2026-08-07", license_path, install_script
            )
            config = ET.parse(output / "config" / "config.xml").getroot()
            package = ET.parse(
                output / "packages" / ifw.PACKAGE_ID / "meta" / "package.xml"
            ).getroot()
            self.assertEqual(config.findtext("Name"), "QGIS+")
            self.assertEqual(package.findtext("Version"), "4.2.1")


class WorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = (ROOT / ".github" / "workflows" / "build.yml").read_text(
            encoding="utf-8"
        )

    def test_build_repackages_official_binaries_instead_of_qgis_source(self) -> None:
        self.assertIn("download.qgis.org", (ROOT / "scripts" / "resolve_binary_packages.py").read_text())
        self.assertIn("stage_windows_binary.py", self.workflow)
        self.assertIn("extract_official_macos.sh", self.workflow)
        self.assertNotIn("vcpkg", self.workflow.lower())
        self.assertNotIn("prepare_source.py", self.workflow)

    def test_cache_is_optional_and_download_is_always_verified(self) -> None:
        self.assertGreaterEqual(self.workflow.count("continue-on-error: true"), 2)
        self.assertEqual(self.workflow.count("download_verified.py"), 2)
        self.assertIn("SHA-256 mismatch", (ROOT / "scripts" / "download_verified.py").read_text())

    def test_release_requires_every_platform(self) -> None:
        self.assertIn("Release requires exactly one package for every platform", self.workflow)
        self.assertIn("*Windows-x64.exe", self.workflow)
        self.assertIn("*macos-intel.dmg", self.workflow)
        self.assertIn("*macos-arm64.dmg", self.workflow)
        self.assertIn("publish_release:", self.workflow)
        self.assertIn("default: true", self.workflow)
        self.assertIn("resolve_release_tag.py", self.workflow)
        self.assertIn('PUBLISH_RELEASE}" == "true"', self.workflow)

    def test_actions_are_pinned_and_no_custom_cancel_api_exists(self) -> None:
        for line in self.workflow.splitlines():
            if "uses:" in line:
                reference = line.split("@", 1)[-1].split()[0]
                self.assertRegex(reference, r"^[0-9a-f]{40}$")
        self.assertIn("cancel-in-progress: false", self.workflow)
        self.assertIn("fail-fast: false", self.workflow)
        self.assertNotIn("gh run cancel", self.workflow)

    def test_windows_uses_matching_msvc_2022_toolchain(self) -> None:
        self.assertIn('-G "Visual Studio 17 2022" -A x64', self.workflow)
        self.assertIn("build/launcher/Release/QGIS+.exe", self.workflow)
        self.assertIn('--theme "themes/QGISPlus Material"', self.workflow)
        self.assertIn('--theme-plugin "plugins/qgisplus_theme"', self.workflow)
        self.assertNotIn("qgisplusstyle.dll", self.workflow)
        self.assertIn(
            "$PSNativeCommandUseErrorActionPreference = $true", self.workflow
        )
        cmake = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
        self.assertIn("if(NOT MSVC)", cmake)
        self.assertIn("must use MSVC", cmake)
        windows_step = self.workflow.split(
            "- name: Configure and build Windows overlay", 1
        )[1].split("- name: Configure and build macOS overlay", 1)[0]
        self.assertNotIn("-G Ninja", windows_step)

    def test_macos_target_is_monterey(self) -> None:
        self.assertIn("CMAKE_OSX_DEPLOYMENT_TARGET=12.0", self.workflow)
        plist = (ROOT / "packaging" / "macos" / "Info.plist.in").read_text()
        self.assertIn("12.0", plist)
        self.assertIn("QGISPlus.icns", plist)
        packaging = (ROOT / "scripts" / "package_macos_binary.sh").read_text()
        self.assertIn("Print :CFBundleExecutable", packaging)
        self.assertIn("Print :CFBundleIconFile", packaging)
        self.assertNotIn("-print -quit", packaging)

    def test_macos_extractor_accepts_versioned_app_and_package_bundles(self) -> None:
        extractor = (ROOT / "scripts" / "extract_official_macos.sh").read_text()
        self.assertIn("-name 'QGIS*.app'", extractor)
        self.assertIn("-name '*.app'", extractor)
        self.assertIn("-name '*.pkg'", extractor)
        self.assertNotIn("-type f -name '*.pkg'", extractor)
        self.assertIn("Mounted DMG root contents", extractor)
        self.assertNotIn("-maxdepth", extractor)

    def test_material_theme_is_compact_and_covers_qgis_widgets(self) -> None:
        theme = ROOT / "themes" / "QGISPlus Material"
        qss = (theme / "style.qss").read_text(encoding="utf-8")
        variables = [
            line.split(":", 1)[0]
            for line in (theme / "variables.qss").read_text(
                encoding="utf-8"
            ).splitlines()
            if line.startswith("@")
        ]
        for required in ("variables.qss", "palette.txt", "LICENSE.qt_material"):
            self.assertTrue((theme / required).is_file())
        for selector in (
            "QgsLayerTreeView",
            "QgsAttributeTableView",
            "QgsMessageBar",
            "QgsAdvancedDigitizingFloater",
            "QgsColorButton",
            "QgsMapCanvas",
            "QComboBox#cmbUITheme",
        ):
            self.assertIn(selector, qss)
        self.assertIn("min-height: 22px", qss)
        self.assertNotIn("height: 40px", qss)
        for index, variable in enumerate(variables):
            self.assertFalse(
                any(later.startswith(variable) for later in variables[index + 1 :]),
                f"QGIS replaces {variable} before a longer variable name",
            )

    def test_macos_package_injects_qgis_theme_without_qt_plugin(self) -> None:
        packaging = (ROOT / "scripts" / "package_macos_binary.sh").read_text()
        self.assertIn("qgis/resources/themes", packaging)
        self.assertIn("qgis/python/plugins", packaging)
        self.assertIn("qgisplus_theme", packaging)
        self.assertIn("QGISPlus Material", packaging)
        self.assertNotIn("install_name_tool", packaging)
        self.assertIn("*qgisplusstyle*", packaging)

    def test_launchers_select_ui_theme_without_style_override(self) -> None:
        macos = (ROOT / "packaging" / "macos" / "QGISPlusLauncher.cpp").read_text()
        windows = (ROOT / "packaging" / "windows" / "QGISPlusLauncher.cpp").read_text()
        self.assertIn('"--globalsettingsfile"', macos)
        self.assertIn('"--profiles-path"', macos)
        self.assertIn('L"--globalsettingsfile"', windows)
        self.assertIn('L"--profiles-path"', windows)
        self.assertNotIn('setenv("QT_STYLE_OVERRIDE"', macos)
        self.assertNotIn('SetEnvironmentVariableW(L"QT_STYLE_OVERRIDE"', windows)

        global_settings = (
            ROOT / "packaging" / "qgisplus-global-settings.ini"
        ).read_text(encoding="utf-8")
        self.assertIn("style=Fusion", global_settings)
        self.assertIn("UITheme=QGISPlus Material", global_settings)
        self.assertIn("[PythonPlugins]", global_settings)
        self.assertIn("qgisplus_theme=true", global_settings)

        registrar = ROOT / "plugins" / "qgisplus_theme" / "plugin.py"
        registrar_source = registrar.read_text(encoding="utf-8")
        self.assertIn("applicationThemeRegistry", registrar_source)
        self.assertIn("setUITheme", registrar_source)
        self.assertNotIn("eventFilter", registrar_source)

    def test_packages_run_real_qgis_theme_verification(self) -> None:
        packaging = (ROOT / "scripts" / "package_macos_binary.sh").read_text()
        verifier = (ROOT / "scripts" / "verify_qgis_theme.py").read_text()
        probe = (ROOT / "scripts" / "qgis_theme_probe.py").read_text()
        self.assertIn("verify_qgis_theme.py", packaging)
        self.assertIn("verify_qgis_theme.py", self.workflow)
        self.assertIn("QGISPLUS_THEME_PROBE_OUTPUT", verifier)
        self.assertIn("QGISPlus Material", probe)
        self.assertIn("QgsLayerTreeView", probe)
        self.assertIn("registered_themes", probe)
        self.assertIn("qlementine_available", probe)
        self.assertIn('result["passed"]', probe)

    def test_packages_verify_options_text_and_combo_width(self) -> None:
        packaging = (ROOT / "scripts" / "package_macos_binary.sh").read_text()
        verifier = (ROOT / "scripts" / "verify_qgis_options_ui.py").read_text()
        probe = (ROOT / "scripts" / "qgis_options_visual_probe.py").read_text()
        self.assertIn("verify_qgis_options_ui.py", packaging)
        self.assertIn("verify_qgis_options_ui.py", self.workflow)
        self.assertIn("disabled_text_contrast", probe)
        self.assertIn("selected_text_contrast", probe)
        self.assertIn("style_popup_has_full_width", probe)
        self.assertIn("theme_popup_has_full_width", probe)
        self.assertIn("menu_checkable_toggle", probe)
        self.assertIn('result.get("passed", False)', verifier)

    def test_windows_waits_for_msi_extraction_and_reads_process_exit_code(self) -> None:
        windows_step = self.workflow.split(
            "- name: Extract and stage official Windows runtime", 1
        )[1].split("- name: Restore Qt Installer Framework cache", 1)[0]
        self.assertIn("Start-Process", windows_step)
        self.assertIn("-Wait -PassThru", windows_step)
        self.assertIn("$msiProcess.ExitCode", windows_step)
        self.assertNotIn("& msiexec.exe", windows_step)

    def test_workflow_matrix_is_valid_json(self) -> None:
        matrix = package_matrix.resolve_matrix("schedule", "true", "true", "true")
        self.assertEqual(json.loads(json.dumps(matrix)), matrix)


if __name__ == "__main__":
    unittest.main()

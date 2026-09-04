from __future__ import annotations

import os
import re
import shutil
import subprocess
import typing
import xml.etree.ElementTree as ET
from pathlib import Path

from biscuit.extensions import Extension

if typing.TYPE_CHECKING:
    from biscuit.api import ExtensionsAPI


class CSharp(Extension):
    """Production C# language support, .NET solution discovery, MSBuild parser, and test runner."""

    def __init__(self, api: ExtensionsAPI) -> None:
        super().__init__(api)
        self.api = api
        self.statusbar_button = None
        self.active_framework = ""
        self.api.logger.info("C# extension loaded.")

    def get_dotnet_version(self) -> str:
        """Query host .NET SDK version."""
        dotnet_bin = shutil.which("dotnet")
        if not dotnet_bin:
            return ""
        try:
            res = subprocess.run([dotnet_bin, "--version"], capture_output=True, text=True, timeout=5)
            return res.stdout.strip()
        except Exception:
            return ""

    def detect_solution_files(self, directory: str) -> list[str]:
        """Scan directory for .sln and .csproj files."""
        found: list[str] = []
        if not os.path.isdir(directory):
            return found
        for f in os.listdir(directory):
            if f.endswith(".sln") or f.endswith(".csproj"):
                found.append(f)
        return found

    def find_solution_or_project(self, start_dir: str | None = None) -> Path | None:
        """Traverse directory tree upward to find .sln or .csproj file."""
        curr = Path(start_dir or os.getcwd()).resolve()
        for parent in [curr] + list(curr.parents):
            for pattern in ["*.sln", "*.csproj"]:
                matches = list(parent.glob(pattern))
                if matches:
                    return matches[0]
        return None

    def parse_solution(self, sln_content: str) -> dict[str, typing.Any]:
        """Parse Visual Studio .sln file content to extract projects, configurations, and GUIDs."""
        result: dict[str, typing.Any] = {
            "projects": [],
            "configurations": [],
        }

        # Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "MyProject", "MyProject\MyProject.csproj", "{GUID}"
        proj_pattern = re.compile(
            r'Project\("\{([A-Fa-f0-9\-]+)\}"\)\s*=\s*"([^"]+)",\s*"([^"]+)",\s*"\{([A-Fa-f0-9\-]+)\}"'
        )
        for match in proj_pattern.finditer(sln_content):
            type_guid, name, rel_path, guid = match.groups()
            result["projects"].append({
                "type_guid": type_guid,
                "name": name,
                "path": rel_path.replace("\\", "/"),
                "guid": guid,
            })

        # Configurations
        config_match = re.search(
            r"GlobalSection\(SolutionConfigurationPlatforms\)\s*=\s*preSolution([\s\S]*?)EndGlobalSection",
            sln_content,
        )
        if config_match:
            for line in config_match.group(1).splitlines():
                clean = line.strip()
                if "=" in clean:
                    cfg = clean.split("=")[0].strip()
                    if cfg and cfg not in result["configurations"]:
                        result["configurations"].append(cfg)

        return result

    def parse_csproj(self, csproj_content: str) -> dict[str, typing.Any]:
        """Parse .csproj XML content to extract target framework, output type, and dependencies."""
        result: dict[str, typing.Any] = {
            "target_framework": "",
            "target_frameworks": [],
            "output_type": "Library",
            "nullable": "",
            "implicit_usings": "",
            "package_references": [],
            "project_references": [],
        }

        try:
            root = ET.fromstring(csproj_content)
        except Exception as e:
            self.api.logger.warning(f"Error parsing .csproj XML: {e}")
            return result

        # Helper to search ignoring namespace
        for elem in root.iter():
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag

            if tag == "TargetFramework" and elem.text:
                result["target_framework"] = elem.text.strip()
            elif tag == "TargetFrameworks" and elem.text:
                result["target_frameworks"] = [tf.strip() for tf in elem.text.split(";") if tf.strip()]
                if not result["target_framework"] and result["target_frameworks"]:
                    result["target_framework"] = result["target_frameworks"][0]
            elif tag == "OutputType" and elem.text:
                result["output_type"] = elem.text.strip()
            elif tag == "Nullable" and elem.text:
                result["nullable"] = elem.text.strip()
            elif tag == "ImplicitUsings" and elem.text:
                result["implicit_usings"] = elem.text.strip()
            elif tag == "PackageReference":
                pkg_name = elem.attrib.get("Include") or elem.attrib.get("Update") or ""
                pkg_version = elem.attrib.get("Version", "")
                if pkg_name:
                    result["package_references"].append({
                        "name": pkg_name,
                        "version": pkg_version,
                    })
            elif tag == "ProjectReference":
                ref_path = elem.attrib.get("Include", "")
                if ref_path:
                    result["project_references"].append(ref_path.replace("\\", "/"))

        return result

    def build_build_command(
        self,
        target: str | None = None,
        config: str = "Debug",
        no_restore: bool = False,
        extra_flags: list[str] | None = None,
    ) -> str:
        """Generate shell command for 'dotnet build'."""
        cmd_parts = ["dotnet", "build"]
        if target:
            cmd_parts.append(f'"{target}"')
        cmd_parts.extend(["-c", config])
        if no_restore:
            cmd_parts.append("--no-restore")
        if extra_flags:
            cmd_parts.extend(extra_flags)
        return " ".join(cmd_parts)

    def parse_msbuild_output(self, output: str) -> dict[str, typing.Any]:
        """Parse MSBuild compiler diagnostic errors, warnings, and summary."""
        result: dict[str, typing.Any] = {
            "succeeded": True,
            "errors": [],
            "warnings": [],
            "error_count": 0,
            "warning_count": 0,
            "time_elapsed": "",
        }

        # Diagnostic regex: Path(line,col): error CODE: Message [Project]
        diag_pattern = re.compile(
            r"^([^\r\n\(]+)\((\d+)(?:,(\d+))?\):\s*(error|warning)\s*([A-Za-z0-9]+):\s*([^\r\n\[]+)(?:\s*\[([^\]]+)\])?",
            re.MULTILINE,
        )

        for match in diag_pattern.finditer(output):
            file_path, line, col, level, code, message, project = match.groups()
            entry = {
                "file": file_path.strip(),
                "line": int(line),
                "col": int(col) if col else 1,
                "level": level.lower(),
                "code": code.strip(),
                "message": message.strip(),
                "project": project.strip() if project else "",
            }
            if level.lower() == "error":
                result["errors"].append(entry)
            else:
                result["warnings"].append(entry)

        # Build outcome summary
        if "Build FAILED." in output:
            result["succeeded"] = False
        elif "Build succeeded." in output:
            result["succeeded"] = True

        err_match = re.search(r"(\d+)\s+Error\(s\)", output)
        if err_match:
            result["error_count"] = int(err_match.group(1))
        else:
            result["error_count"] = len(result["errors"])

        warn_match = re.search(r"(\d+)\s+Warning\(s\)", output)
        if warn_match:
            result["warning_count"] = int(warn_match.group(1))
        else:
            result["warning_count"] = len(result["warnings"])

        time_match = re.search(r"Time Elapsed\s+([\d:\.]+)", output)
        if time_match:
            result["time_elapsed"] = time_match.group(1)

        if result["error_count"] > 0:
            result["succeeded"] = False

        return result

    def build_run_command(
        self,
        project_path: str | None = None,
        config: str | None = None,
        args: list[str] | None = None,
    ) -> str:
        """Generate shell command for 'dotnet run'."""
        cmd_parts = ["dotnet", "run"]
        if project_path:
            cmd_parts.extend(["--project", f'"{project_path}"'])
        if config:
            cmd_parts.extend(["-c", config])
        if args:
            cmd_parts.append("--")
            cmd_parts.extend(f'"{a}"' if " " in a else a for a in args)
        return " ".join(cmd_parts)

    def build_test_command(
        self,
        target: str | None = None,
        filter_expr: str | None = None,
        no_build: bool = False,
    ) -> str:
        """Generate shell command for 'dotnet test'."""
        cmd_parts = ["dotnet", "test"]
        if target:
            cmd_parts.append(f'"{target}"')
        if filter_expr:
            cmd_parts.extend(["--filter", f'"{filter_expr}"'])
        if no_build:
            cmd_parts.append("--no-build")
        return " ".join(cmd_parts)

    def parse_test_output(self, output: str) -> dict[str, typing.Any]:
        """Parse 'dotnet test' summary and test outcomes."""
        result: dict[str, typing.Any] = {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "duration": "",
            "tests": [],
        }

        # Outcome summary line: Passed! - Failed: 0, Passed: 15, Skipped: 0, Total: 15, Duration: 120 ms
        summary_match = re.search(
            r"(Passed|Failed)!\s+-\s+Failed:\s*(\d+),\s*Passed:\s*(\d+),\s*Skipped:\s*(\d+),\s*Total:\s*(\d+)(?:,\s*Duration:\s*([^\r\n]+))?",
            output,
        )
        if summary_match:
            result["failed"] = int(summary_match.group(2))
            result["passed"] = int(summary_match.group(3))
            result["skipped"] = int(summary_match.group(4))
            result["total"] = int(summary_match.group(5))
            if summary_match.group(6):
                result["duration"] = summary_match.group(6).strip()

        # Individual test lines
        item_pattern = re.compile(r"^\s*(Passed|Failed|Skipped)\s+([^\s\[]+)(?:\s*\[([\d\w\s]+)\])?", re.MULTILINE)
        for match in item_pattern.finditer(output):
            status, name, duration = match.groups()
            result["tests"].append({
                "name": name.strip(),
                "status": status.upper(),
                "duration": duration.strip() if duration else "",
            })

        if result["total"] == 0 and result["tests"]:
            result["total"] = len(result["tests"])
            result["passed"] = sum(1 for t in result["tests"] if t["status"] == "PASSED")
            result["failed"] = sum(1 for t in result["tests"] if t["status"] == "FAILED")
            result["skipped"] = sum(1 for t in result["tests"] if t["status"] == "SKIPPED")

        return result

    def install(self) -> None:
        """Register commands, statusbar widget, and editor bindings."""
        # 1. Commands
        self.api.commands.register_command("csharp.build", lambda: self.build_command_handler())
        self.api.commands.register_command("csharp.run", lambda: self.run_command_handler())
        self.api.commands.register_command("csharp.test", lambda: self.test_command_handler())
        self.api.commands.register_command("csharp.restore", lambda: self.restore_command_handler())
        self.api.commands.register_command("csharp.clean", lambda: self.clean_command_handler())

        # 2. Core registrations
        self.api.register_comment_prefix("csharp", "//")
        self.api.register_langserver("csharp", "csharp-ls")
        self.api.register_run_command("csharp", "dotnet run")

        # 3. Statusbar
        sdk_version = self.get_dotnet_version()
        label = f".NET {sdk_version}".strip() if sdk_version else ".NET Ready"
        try:
            self.statusbar_button = self.api.statusbar.add_button(
                text=label,
                icon="symbol-method",
                callback=self.show_dotnet_info_command,
                description=".NET Solution & Project",
            )
            if self.statusbar_button:
                self.statusbar_button.show()
        except Exception as e:
            self.api.logger.warning(f"Could not initialize C# statusbar button: {e}")

        self.api.logger.info("C# extension installed.")

    def build_command_handler(self) -> None:
        """Command: execute dotnet build."""
        cmd = self.build_build_command()
        if hasattr(self.api, "terminalmanager") and self.api.terminalmanager:
            self.api.terminalmanager.open_terminal(command=cmd)
        self.api.logger.info(f"Triggered dotnet build: {cmd}")

    def run_command_handler(self) -> None:
        """Command: execute dotnet run."""
        cmd = self.build_run_command()
        if hasattr(self.api, "terminalmanager") and self.api.terminalmanager:
            self.api.terminalmanager.open_terminal(command=cmd)

    def test_command_handler(self) -> None:
        """Command: execute dotnet test."""
        cmd = self.build_test_command()
        if hasattr(self.api, "terminalmanager") and self.api.terminalmanager:
            self.api.terminalmanager.open_terminal(command=cmd)

    def restore_command_handler(self) -> None:
        """Command: execute dotnet restore."""
        cmd = "dotnet restore"
        if hasattr(self.api, "terminalmanager") and self.api.terminalmanager:
            self.api.terminalmanager.open_terminal(command=cmd)

    def clean_command_handler(self) -> None:
        """Command: execute dotnet clean."""
        cmd = "dotnet clean"
        if hasattr(self.api, "terminalmanager") and self.api.terminalmanager:
            self.api.terminalmanager.open_terminal(command=cmd)

    def show_dotnet_info_command(self) -> dict[str, str]:
        """Display .NET environment and project info."""
        sdk = self.get_dotnet_version()
        info = {"sdk": sdk}
        sol = self.find_solution_or_project()
        if sol:
            info["target"] = str(sol)
            self.api.notifications.info(f".NET SDK: {sdk or 'installed'} | Active Target: {sol.name}")
        else:
            self.api.notifications.info(f".NET SDK: {sdk or 'ready'}")
        return info

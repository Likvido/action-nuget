"""Compares each project's public API with the newest version of its package listed on nuget.org.

Packs every project in PROJECTS (one path per line) with .NET package validation, the baseline being the
newest listed version of its package id on nuget.org, whatever version the project itself has. Exits 1
when package validation reports a breaking change, or when a project could not be compared; 0 otherwise.
A package that is not on nuget.org has no baseline and passes.
"""

import gzip
import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request

REGISTRATION = "https://api.nuget.org/v3/registration5-gz-semver2/{id}/index.json"

# Breaking changes only: CP0xxx (API compatibility) and PKVxxx (package validation). CP1xxx says a reference
# could not be resolved, which is about the build, not the API.
BREAK = re.compile(r"\berror ((?:CP0\d{3})|(?:PKV\d+)): (.*?)(?: \[[^\]\[]*\])?\s*$")

# GitHub keeps up to 10 error annotations per step.
MAX_ANNOTATIONS = 9


class NuGetUnreadable(Exception):
    pass


def fetch_json(url):
    """The JSON at url, None on 404. Retries other failures three times."""
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"Accept-Encoding": "gzip", "User-Agent": "likvido-action-nuget"})
            with urllib.request.urlopen(request, timeout=30) as response:
                data = response.read()
                if response.headers.get("Content-Encoding") == "gzip" or data[:2] == b"\x1f\x8b":
                    data = gzip.decompress(data)
                return json.loads(data)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            last = f"HTTP {error.code}"
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as error:
            last = str(error)
        time.sleep(5 * (attempt + 1))
    raise NuGetUnreadable(f"{url} could not be read: {last}")


def version_key(text):
    """NuGet's ordering of a version: numbers first, then a stable version above its pre-releases."""
    text = text.split("+", 1)[0]
    release, _, pre = text.partition("-")
    numbers = [int(part) for part in release.split(".")]
    numbers += [0] * (4 - len(numbers))
    labels = []
    for label in pre.split(".") if pre else []:
        labels.append((0, int(label), "") if label.isdigit() else (1, 0, label.lower()))
    return (numbers, 1 if not pre else 0, labels)


def baseline(package_id):
    """The newest listed stable version of the package on nuget.org, else its newest listed pre-release, else None."""
    index = fetch_json(REGISTRATION.format(id=package_id.lower()))
    if index is None:
        return None
    listed = []
    for page in index.get("items", []):
        items = page.get("items")
        if items is None:
            items = (fetch_json(page["@id"]) or {}).get("items", [])
        for item in items:
            entry = item.get("catalogEntry", {})
            if entry.get("listed", True):
                listed.append(entry["version"])
    if not listed:
        return None
    stable = [v for v in listed if "-" not in v.split("+", 1)[0]]
    return max(stable or listed, key=version_key)


def escape_data(text):
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def escape_property(text):
    return escape_data(text).replace(":", "%3A").replace(",", "%2C")


def annotate(level, title, message):
    print(f"::{level} title={escape_property(title)}::{escape_data(message)}", flush=True)


def show_output(text):
    """Prints a tool's output indented, with workflow commands off, so no line of it is read as a command or matched
    by a problem matcher into a second annotation."""
    token = secrets.token_hex(16)
    print(f"::stop-commands::{token}")
    for line in text.splitlines():
        print("  " + line)
    print(f"::{token}::", flush=True)


def run(args):
    print("$ " + " ".join(args), flush=True)
    result = subprocess.run(args, capture_output=True, text=True)
    output = result.stdout + result.stderr
    show_output(output)
    return result.returncode, output


def fence(lines):
    body = "\n".join(lines).replace("~~~", "~ ~ ~")
    return f"~~~\n{body}\n~~~"


def main():
    projects = [line.strip() for line in os.environ.get("PROJECTS", "").splitlines() if line.strip()]
    if not projects:
        annotate("error", "api-compatibility", "No project was given to compare.")
        return 1

    out_dir = os.path.join(os.environ.get("RUNNER_TEMP", "/tmp"), "api-compatibility")
    summary = ["## API compatibility", ""]
    failed = False
    annotations = 0
    total = 0

    for project in projects:
        code, output = run(["dotnet", "msbuild", project, "-getProperty:PackageId", "-p:Configuration=Release", "-nologo"])
        package_id = output.strip().splitlines()[-1].strip() if code == 0 and output.strip() else ""
        if code != 0 or not re.fullmatch(r"[A-Za-z0-9._-]+", package_id):
            annotate("error", "api-compatibility", f"The package id of {project} could not be read, so its API was not compared.")
            summary.append(f"- `{project}`: its package id could not be read, so its API was not compared.")
            failed = True
            continue

        try:
            version = baseline(package_id)
        except NuGetUnreadable as error:
            annotate("error", "api-compatibility", f"nuget.org could not be read for {package_id}, so its API was not compared: {error}")
            summary.append(f"- **{package_id}**: nuget.org could not be read, so its API was not compared.")
            failed = True
            continue

        if version is None:
            annotate("notice", "api-compatibility", f"{package_id} has no listed version on nuget.org, so there is nothing to compare its API with.")
            summary.append(f"- **{package_id}**: no listed version on nuget.org, so there is nothing to compare its API with.")
            continue

        code, output = run([
            "dotnet", "pack", project, "-c", "Release", "-o", out_dir, "-nologo", "-tl:off",
            "-p:EnablePackageValidation=true",
            f"-p:PackageValidationBaselineVersion={version}",
        ])

        breaks = []
        for line in output.splitlines():
            match = BREAK.search(line)
            if match:
                diagnostic = f"{match.group(1)}: {match.group(2).strip()}"
                if diagnostic not in breaks:
                    breaks.append(diagnostic)

        if breaks:
            failed = True
            total += len(breaks)
            for diagnostic in breaks:
                if annotations < MAX_ANNOTATIONS:
                    annotate("error", f"API break in {package_id}", diagnostic)
                    annotations += 1
            summary.append(f"- **{package_id}**: its public API breaks against {version} on nuget.org ({len(breaks)} {'diagnostic' if len(breaks) == 1 else 'diagnostics'}):")
            summary.append("")
            summary.append(fence(breaks))
            summary.append("")
        elif code != 0:
            failed = True
            annotate("error", "api-compatibility", f"{package_id} did not pack, so its API was not compared; see the log.")
            summary.append(f"- **{package_id}**: it did not pack, so its API was not compared; see the log.")
        else:
            summary.append(f"- **{package_id}**: no breaking change against {version} on nuget.org.")

    if total > annotations:
        annotate("error", "api-compatibility", "There are more breaking changes than are shown as annotations; the job summary lists them all.")

    if failed:
        summary += ["", "A breaking change needs a new major version in `version.props`, which a person merges, or the old API kept. "
                    "The comparison is with the newest version on nuget.org, so this check stays failed until that major is published."]

    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a") as f:
            f.write("\n".join(summary) + "\n")
    print("\n".join(summary))

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

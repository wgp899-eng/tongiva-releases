#!/usr/bin/env python3
"""Build/sign/publish helper for the Tongiva iOS GitHub Actions pipeline.

All signing happens on the GitHub-hosted macOS runner.  The only local input
was the one-time export of the Apple Distribution identity into the
IOS_DISTRIBUTION_P12 secret (the secret already existed in this repository;
the workflow proves the imported identity matches the team certificate).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

BUNDLE_ID = "com.vexlink.liaoqiao.ios"
TEAM_ID = "5V4M77FFRV"
PROFILE_NAME = "Tongiva Ad Hoc 6 Devices 20261101T025724Z"
REPO = "wgp899-eng/tongiva-releases"
TAG = "ios-updates"
API = "https://api.github.com"
ASSET_ROOT = f"https://github.com/{REPO}/releases/download/{TAG}/"
USER_AGENT = "Tongiva-iOS-GitHub-Actions"
CHUNK = 1024 * 1024


class PipelineError(RuntimeError):
    pass


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def run(args: list[str], *, cwd: Path | None = None, timeout: int = 600,
        capture: bool = True) -> subprocess.CompletedProcess:
    log("+ " + " ".join(str(a) for a in args))
    result = subprocess.run(
        [str(a) for a in args],
        cwd=str(cwd) if cwd else None,
        capture_output=capture,
        text=True,
        timeout=timeout,
        check=False,
    )
    if capture:
        if result.stdout:
            log(result.stdout.rstrip())
        if result.stderr:
            log(result.stderr.rstrip())
    if result.returncode != 0:
        raise PipelineError(f"command failed ({result.returncode}): {' '.join(str(a) for a in args)}")
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha1_bytes(value: bytes) -> str:
    return hashlib.sha1(value).hexdigest().upper()


def profile_dict(path: Path) -> dict:
    result = subprocess.run(
        ["security", "cms", "-D", "-i", str(path)],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise PipelineError(
            "cannot decode provisioning profile: " + result.stderr.decode("utf-8", "replace")
        )
    return plistlib.loads(result.stdout)


def validate_profile(profile: dict) -> None:
    if profile.get("Name") != PROFILE_NAME:
        raise PipelineError(f"unexpected provisioning profile name: {profile.get('Name')!r}")
    if profile.get("TeamIdentifier") != [TEAM_ID]:
        raise PipelineError("provisioning profile team mismatch")
    if profile.get("ProvisionsAllDevices"):
        raise PipelineError("enterprise profile is not allowed here")
    devices = profile.get("ProvisionedDevices") or []
    if not devices:
        raise PipelineError("provisioning profile has no registered devices")
    if profile.get("Entitlements", {}).get("application-identifier") != f"{TEAM_ID}.{BUNDLE_ID}":
        raise PipelineError("provisioning profile application-identifier mismatch")
    if profile.get("Entitlements", {}).get("get-task-allow") is not False:
        raise PipelineError("provisioning profile is not an Ad Hoc distribution profile")
    expires = profile.get("ExpirationDate")
    if not isinstance(expires, dt.datetime):
        raise PipelineError("provisioning profile has no expiration date")
    if expires.replace(tzinfo=dt.timezone.utc) <= dt.datetime.now(dt.timezone.utc):
        raise PipelineError("provisioning profile has expired")


def extract_ipa(ipa: Path, destination: Path) -> None:
    with zipfile.ZipFile(ipa) as archive:
        infos = archive.infolist()
        if len(infos) > 200000 or sum(i.file_size for i in infos) > 3 * 1024 ** 3:
            raise PipelineError("IPA exceeds extraction limit")
        for item in infos:
            path = PurePosixPath(item.filename)
            mode = item.external_attr >> 16
            if path.is_absolute() or ".." in path.parts or "\\" in item.filename or stat.S_ISLNK(mode):
                raise PipelineError(f"unsafe IPA member: {item.filename}")
            archive.extract(item, destination)
            target = destination.joinpath(*path.parts)
            if not item.is_dir() and mode & 0o777:
                target.chmod(mode & 0o777)


def single_app(root: Path) -> Path:
    payload = root / "Payload"
    if not payload.is_dir():
        raise PipelineError("IPA has no Payload directory")
    apps = [p for p in payload.iterdir() if p.suffix == ".app" and p.is_dir()]
    if len(apps) != 1:
        raise PipelineError(f"expected exactly one .app in Payload, found {len(apps)}")
    app = apps[0]
    if list(app.rglob("*.appex")) or [p for p in app.rglob("*.app") if p != app]:
        raise PipelineError("nested applications/extensions require separate provisioning profiles")
    return app


def entitlements_of(app: Path) -> dict:
    result = subprocess.run(
        ["codesign", "-d", "--entitlements", ":-", str(app)],
        capture_output=True,
        check=False,
    )
    raw = result.stdout or result.stderr
    if not raw.strip():
        raise PipelineError("codesign returned no entitlements")
    try:
        return plistlib.loads(raw)
    except Exception as error:  # noqa: BLE001
        raise PipelineError(f"cannot parse app entitlements: {error}") from error


def signature_info(app: Path) -> dict:
    result = subprocess.run(
        ["codesign", "-dvvv", str(app)],
        capture_output=True,
        text=True,
        check=False,
    )
    text = (result.stdout or "") + (result.stderr or "")
    info = {"output": text.strip()}
    for key in ("CDHash", "TeamIdentifier", "Identifier", "Runtime Version"):
        match = re.search(rf"^{re.escape(key)}=(.+)$", text, re.MULTILINE)
        if match:
            info[key] = match.group(1).strip()
    info["Authority"] = re.findall(r"^Authority=(.+)$", text, re.MULTILINE)
    if result.returncode != 0:
        raise PipelineError("codesign -dvvv failed")
    return info


def signing_certificate(app: Path) -> bytes:
    with tempfile.TemporaryDirectory(prefix="tongiva-cert-") as tmp:
        prefix = Path(tmp) / "cert"
        result = subprocess.run(
            ["codesign", "-d", f"--extract-certificates={prefix}", str(app)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise PipelineError("codesign --extract-certificates failed: " + result.stderr.strip())
        leaf = Path(str(prefix) + "0")
        if not leaf.is_file():
            raise PipelineError("codesign did not emit a leaf certificate")
        return leaf.read_bytes()


def verify_app(app: Path, profile: dict, expected_entitlements: dict, build: int) -> dict:
    info_path = app / "Info.plist"
    info = plistlib.loads(info_path.read_bytes())
    if info.get("CFBundleIdentifier") != BUNDLE_ID:
        raise PipelineError("unexpected bundle identifier: " + str(info.get("CFBundleIdentifier")))
    if str(info.get("CFBundleVersion")) != str(build):
        raise PipelineError(f"bundle build {info.get('CFBundleVersion')} != requested {build}")
    embedded = app / "embedded.mobileprovision"
    if not embedded.is_file():
        raise PipelineError("app has no embedded.mobileprovision")
    embedded_profile = profile_dict(embedded)
    if embedded_profile.get("UUID") != profile.get("UUID"):
        raise PipelineError("embedded provisioning profile UUID mismatch")
    if not (app / info["CFBundleExecutable"]).is_file():
        raise PipelineError("app executable is missing")

    run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", app])
    actual_entitlements = entitlements_of(app)
    if actual_entitlements != expected_entitlements:
        raise PipelineError(
            "signed entitlements do not match the requested entitlements: "
            + json.dumps({"actual": actual_entitlements, "expected": expected_entitlements}, sort_keys=True)
        )

    leaf = signing_certificate(app)
    allowed = {sha1_bytes(cert) for cert in profile.get("DeveloperCertificates", [])}
    if sha1_bytes(leaf) not in allowed:
        raise PipelineError("app is not signed by a certificate embedded in the provisioning profile")

    sig = signature_info(app)
    return {
        "bundleIdentifier": BUNDLE_ID,
        "build": int(build),
        "version": info.get("CFBundleShortVersionString"),
        "minimumOSVersion": info.get("MinimumOSVersion"),
        "cdhash": sig.get("CDHash"),
        "teamIdentifier": sig.get("TeamIdentifier"),
        "authority": sig.get("Authority", []),
        "signingCertificateSHA1": sha1_bytes(leaf),
        "signingCertificateSHA256": hashlib.sha256(leaf).hexdigest(),
        "profileName": embedded_profile.get("Name"),
        "profileUUID": embedded_profile.get("UUID"),
        "profileExpiration": embedded_profile.get("ExpirationDate").isoformat(),
        "deviceCount": len(embedded_profile.get("ProvisionedDevices") or []),
        "entitlements": actual_entitlements,
        "codesignOutput": sig.get("output"),
    }


def sign_app(app: Path, profile_path: Path, entitlements_path: Path, build: int) -> None:
    info_path = app / "Info.plist"
    info = plistlib.loads(info_path.read_bytes())
    if info.get("CFBundleIdentifier") != BUNDLE_ID:
        raise PipelineError("source app bundle identifier mismatch")
    if str(info.get("CFBundleVersion")) != str(build):
        info["CFBundleVersion"] = str(build)
        info_path.write_bytes(plistlib.dumps(info, fmt=plistlib.FMT_BINARY, sort_keys=False))
        log(f"set CFBundleVersion to {build}")

    shutil.copyfile(profile_path, app / "embedded.mobileprovision")
    expected = plistlib.loads(Path(entitlements_path).read_bytes())

    nested = sorted(
        [*app.rglob("*.framework"), *app.rglob("*.dylib")],
        key=lambda p: len(p.parts),
        reverse=True,
    )
    for item in nested:
        run(["codesign", "--force", "--sign", "Apple Distribution", item])

    executable = app / info["CFBundleExecutable"]
    executable.chmod(executable.stat().st_mode | 0o111)
    run([
        "codesign", "--force", "--options", "runtime",
        "--sign", "Apple Distribution",
        "--entitlements", str(entitlements_path),
        app,
    ])
    run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", app])
    actual = entitlements_of(app)
    if actual != expected:
        raise PipelineError("codesign did not preserve the requested entitlements")


def zip_ipa(root: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted((root / "Payload").rglob("*")):
            if path.is_dir():
                continue
            arcname = path.relative_to(root).as_posix()
            info = zipfile.ZipInfo.from_file(path, arcname)
            info.compress_type = zipfile.ZIP_DEFLATED
            if path.is_symlink():
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, os.readlink(path))
            else:
                with path.open("rb") as handle:
                    archive.writestr(info, handle.read(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)


def manifest_bytes(ipa_name: str, build: int) -> bytes:
    value = {
        "items": [
            {
                "assets": [
                    {"kind": "software-package", "url": ASSET_ROOT + ipa_name},
                ],
                "metadata": {
                    "bundle-identifier": BUNDLE_ID,
                    "bundle-version": str(build),
                    "kind": "software",
                    "title": "Tongiva",
                },
            }
        ]
    }
    return plistlib.dumps(value, fmt=plistlib.FMT_XML, sort_keys=False)


def feed_bytes(ipa_name: str, build: int, version: str, minimum_os: str,
               size: int, digest: str, manifest: bytes, notes: str,
               profile: dict) -> bytes:
    devices = sorted(str(d) for d in profile.get("ProvisionedDevices") or [])
    value = {
        "schemaVersion": 1,
        "platform": "ios",
        "bundleIdentifier": BUNDLE_ID,
        "version": version,
        "build": build,
        "minimumOSVersion": minimum_os,
        "name": ipa_name,
        "url": ASSET_ROOT + ipa_name,
        "size": size,
        "manifestURL": ASSET_ROOT + f"Tongiva-iOS-v{build}.plist",
        "manifestSHA256": hashlib.sha256(manifest).hexdigest(),
        "sha256": digest,
        "releaseNotes": notes.strip(),
        "deviceSetSHA256": hashlib.sha256("\n".join(devices).encode()).hexdigest(),
        "deviceCount": len(devices),
    }
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def read_notes(args: argparse.Namespace) -> str:
    if args.notes_file:
        return Path(args.notes_file).read_text(encoding="utf-8")
    return args.notes or ""


def command_package(args: argparse.Namespace) -> dict:
    profile_path = Path(args.profile)
    entitlements_path = Path(args.entitlements)
    profile = profile_dict(profile_path)
    validate_profile(profile)
    expected_entitlements = plistlib.loads(entitlements_path.read_bytes())
    notes = read_notes(args)
    if not notes.strip():
        raise PipelineError("release notes are required")
    if len(notes) > 12000:
        raise PipelineError("release notes are too long")
    build = int(args.build)
    if build <= 0:
        raise PipelineError("build number must be positive")

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tongiva-package-") as tmp:
        root = Path(tmp)
        if args.source_ipa:
            log(f"extracting {args.source_ipa}")
            extract_ipa(Path(args.source_ipa), root)
        elif args.app:
            app_source = Path(args.app)
            if not app_source.is_dir():
                raise PipelineError("--app is not a directory")
            app_copy = root / "Payload" / app_source.name
            app_copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(app_source, app_copy, symlinks=True)
        else:
            raise PipelineError("one of --source-ipa or --app is required")

        app = single_app(root)
        sign_app(app, profile_path, entitlements_path, build)
        info = plistlib.loads((app / "Info.plist").read_bytes())
        verify = verify_app(app, profile, expected_entitlements, build)

        ipa_name = f"Tongiva-iOS-v{build}.ipa"
        ipa_path = output / ipa_name
        zip_ipa(root, ipa_path)

    size = ipa_path.stat().st_size
    digest = sha256_file(ipa_path)
    manifest = manifest_bytes(ipa_name, build)
    manifest_path = output / f"Tongiva-iOS-v{build}.plist"
    manifest_path.write_bytes(manifest)
    feed = feed_bytes(
        ipa_name, build, str(info.get("CFBundleShortVersionString") or "1.0"),
        str(info.get("MinimumOSVersion") or "15.0"), size, digest, manifest, notes, profile,
    )
    feed_path = output / "ios-update.json"
    feed_path.write_bytes(feed)

    with zipfile.ZipFile(ipa_path) as archive:
        bad = archive.testzip()
        if bad:
            raise PipelineError("generated IPA is corrupt at " + bad)

    result = {
        "build": build,
        "name": ipa_name,
        "size": size,
        "sha256": digest,
        "ipa": str(ipa_path),
        "plist": str(manifest_path),
        "plistSHA256": hashlib.sha256(manifest).hexdigest(),
        "json": str(feed_path),
        "jsonSHA256": hashlib.sha256(feed).hexdigest(),
        "cdhash": verify["cdhash"],
        "signingCertificateSHA256": verify["signingCertificateSHA256"],
        "profileUUID": verify["profileUUID"],
        "deviceCount": verify["deviceCount"],
        "entitlements": verify["entitlements"],
    }
    (output / "build-info.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    log(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def command_verify(args: argparse.Namespace) -> dict:
    profile = profile_dict(Path(args.profile))
    validate_profile(profile)
    expected = plistlib.loads(Path(args.entitlements).read_bytes())
    with tempfile.TemporaryDirectory(prefix="tongiva-verify-") as tmp:
        root = Path(tmp)
        extract_ipa(Path(args.ipa), root)
        app = single_app(root)
        result = verify_app(app, profile, expected, int(args.build))
    result["ipa"] = str(args.ipa)
    result["ipaSize"] = Path(args.ipa).stat().st_size
    result["ipaSHA256"] = sha256_file(Path(args.ipa))
    result["plistSHA256"] = hashlib.sha256(Path(args.plist).read_bytes()).hexdigest() if args.plist else None
    log(json.dumps(result, ensure_ascii=False, indent=2))
    return result


# ---------------------------------------------------------------- GitHub API

def token() -> str:
    value = os.environ.get("GITHUB_TOKEN", "").strip()
    if not value:
        raise PipelineError("GITHUB_TOKEN is required")
    return value


def api(method: str, path: str, body: object | None = None, *,
        content_type: str = "application/json", data=None,
        content_length: int | None = None, accept: str = "application/vnd.github+json",
        timeout: int = 300) -> object | None:
    url = path if path.startswith("https://") else API + path
    parsed = urllib.parse.urlsplit(url)
    if parsed.hostname not in {"api.github.com", "uploads.github.com"}:
        raise PipelineError("refusing non-GitHub API destination: " + url)
    headers = {
        "Authorization": "Bearer " + token(),
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": USER_AGENT,
        "Content-Type": content_type,
    }
    if content_length is not None:
        headers["Content-Length"] = str(content_length)
    payload = body
    if body is not None and not isinstance(body, (bytes, bytearray)) and data is None:
        payload = json.dumps(body, ensure_ascii=False).encode()
    elif data is not None:
        payload = data
    request = urllib.request.Request(url, data=payload, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read(4096).decode("utf-8", "replace")
        raise PipelineError(f"GitHub API {method} {url} -> HTTP {error.code}: {detail}") from error
    if not raw:
        return None
    return json.loads(raw)


def release() -> dict:
    value = api("GET", f"/repos/{REPO}/releases/tags/{TAG}")
    if not isinstance(value, dict) or "assets" not in value:
        raise PipelineError("unexpected release response")
    return value


def asset_by_name(rel: dict, name: str) -> dict | None:
    return next((a for a in rel["assets"] if a.get("name") == name), None)


def download_public(url: str, target: Path, *, expected_size: int | None = None,
                    expected_sha256: str | None = None, timeout: int = 300) -> str:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not (parsed.hostname in {"github.com", "objects.githubusercontent.com"}
                                        or (parsed.hostname or "").endswith(".githubusercontent.com")):
        raise PipelineError("refusing non-GitHub download destination: " + url)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Cache-Control": "no-cache, no-store, max-age=0",
            "Pragma": "no-cache",
        },
    )
    digest = hashlib.sha256()
    received = 0
    target.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(request, timeout=timeout) as response, target.open("wb") as handle:
        while chunk := response.read(CHUNK):
            received += len(chunk)
            if expected_size is not None and received > expected_size:
                raise PipelineError("download exceeded advertised size")
            handle.write(chunk)
            digest.update(chunk)
    if expected_size is not None and received != expected_size:
        raise PipelineError(f"download size {received} != advertised {expected_size}")
    actual = digest.hexdigest()
    if expected_sha256 and actual.lower() != expected_sha256.lower():
        raise PipelineError(f"download sha256 {actual} != expected {expected_sha256}")
    return actual


def command_download(args: argparse.Namespace) -> dict:
    rel = release()
    asset = asset_by_name(rel, args.asset)
    if not asset:
        raise PipelineError(f"release asset not found: {args.asset}")
    expected = args.sha256.strip().lower() if args.sha256 else None
    if not expected and asset.get("digest"):
        expected = asset["digest"].removeprefix("sha256:")
    if not expected:
        raise PipelineError("no sha256 available; pass --sha256 explicitly")
    target = Path(args.output)
    actual = download_public(
        asset["browser_download_url"], target,
        expected_size=int(asset["size"]), expected_sha256=expected,
    )
    result = {"asset": args.asset, "id": asset["id"], "size": target.stat().st_size,
              "sha256": actual, "path": str(target)}
    log(json.dumps(result, indent=2))
    return result


def upload_asset(rel: dict, path: Path, name: str, overwrite: bool) -> dict:
    existing = asset_by_name(rel, name)
    digest = sha256_file(path)
    size = path.stat().st_size
    if existing:
        if existing.get("digest") == "sha256:" + digest and existing.get("size") == size:
            log(f"asset already current: {name}")
            return existing
        if not overwrite:
            raise PipelineError(f"asset already exists and overwrite is false: {name}")
        log(f"deleting existing asset {name} (id {existing['id']})")
        api("DELETE", f"/repos/{REPO}/releases/assets/{existing['id']}")
    url = rel["upload_url"].split("{", 1)[0] + "?" + urllib.parse.urlencode({"name": name})
    log(f"uploading {name} ({size} bytes) to {url}")
    with path.open("rb") as handle:
        result = api(
            "POST", url, data=handle, content_type="application/octet-stream",
            content_length=size, accept="application/vnd.github+json", timeout=900,
        )
    if not isinstance(result, dict):
        raise PipelineError("empty upload response")
    if result.get("size") != size:
        raise PipelineError("uploaded asset size mismatch")
    if result.get("digest") and result["digest"] != "sha256:" + digest:
        raise PipelineError("uploaded asset digest mismatch")
    return result


def command_publish(args: argparse.Namespace) -> dict:
    ipa = Path(args.ipa)
    plist = Path(args.plist)
    feed = Path(args.json)
    build = int(args.build)
    notes = read_notes(args)
    if not notes.strip():
        raise PipelineError("release notes are required")
    for path in (ipa, plist, feed):
        if not path.is_file():
            raise PipelineError("missing publish input: " + str(path))

    rel = release()
    upload_asset(rel, ipa, ipa.name, args.overwrite)
    upload_asset(rel, plist, plist.name, args.overwrite)

    rel = release()
    old_feed = asset_by_name(rel, "ios-update.json")
    if old_feed:
        old_build = None
        try:
            with tempfile.TemporaryDirectory(prefix="tongiva-old-feed-") as tmp:
                old_path = Path(tmp) / "ios-update.json"
                download_public(
                    old_feed["browser_download_url"] + "?cb=" + str(time.time_ns()),
                    old_path,
                )
                old_build = json.loads(old_path.read_text()).get("build")
        except Exception:  # noqa: BLE001
            old_build = None
        if old_build == build:
            # Same build number: replace the feed atomically by name.  Do not
            # keep a historical feed that would point at the replaced IPA.
            upload_asset(rel, feed, "ios-update.json", True)
        else:
            staged_name = f"ios-update-next-v{build}.json"
            staged = upload_asset(rel, feed, staged_name, True)
            archive_name = f"ios-update-v{old_build}.json" if isinstance(old_build, int) else f"ios-update-old-{old_feed['id']}.json"
            if asset_by_name(rel, archive_name):
                archive_name = f"ios-update-v{old_build}-snapshot-{old_feed['id']}.json"
            api("PATCH", f"/repos/{REPO}/releases/assets/{old_feed['id']}", {"name": archive_name})
            try:
                api("PATCH", f"/repos/{REPO}/releases/assets/{staged['id']}", {"name": "ios-update.json"})
            except Exception:
                api("PATCH", f"/repos/{REPO}/releases/assets/{old_feed['id']}", {"name": "ios-update.json"})
                raise
    else:
        upload_asset(rel, feed, "ios-update.json", args.overwrite)

    body = (
        f"iOS 独立更新通道，当前推荐版本 v{build}。\n\n{notes.strip()}\n\n"
        "首次安装和更新使用同一完整包。请保留原应用进行覆盖安装。历史版本保留，本通道不设为仓库 Latest。"
    )
    api("PATCH", f"/repos/{REPO}/releases/{rel['id']}", {
        "name": f"Tongiva iOS 更新通道（当前 v{build}）",
        "body": body,
        "make_latest": "false",
    })

    # Confirm the public feed now serves the new build/hash.
    expected_digest = sha256_file(ipa)
    observed = None
    for attempt in range(12):
        try:
            with tempfile.TemporaryDirectory(prefix="tongiva-feed-") as tmp:
                target = Path(tmp) / "ios-update.json"
                download_public(
                    ASSET_ROOT + "ios-update.json?cb=" + str(time.time_ns()),
                    target,
                )
                observed = json.loads(target.read_text())
            if observed.get("build") == build and observed.get("sha256") == expected_digest:
                break
            log(
                f"feed verification attempt {attempt + 1}: "
                f"build={observed.get('build')} sha256={observed.get('sha256')}"
            )
        except Exception as error:  # noqa: BLE001
            log(f"feed verification attempt {attempt + 1} failed: {error}")
        time.sleep(5)
    if not observed or observed.get("build") != build or observed.get("sha256") != expected_digest:
        raise PipelineError("published ios-update.json does not point at the new IPA")

    result = {
        "build": build,
        "releaseId": rel["id"],
        "ipa": {"name": ipa.name, "size": ipa.stat().st_size, "sha256": expected_digest},
        "plist": {"name": plist.name, "size": plist.stat().st_size, "sha256": sha256_file(plist)},
        "feed": {"name": "ios-update.json", "sha256": sha256_file(feed)},
        "feedBuild": observed.get("build"),
        "feedSHA256": observed.get("sha256"),
        "downloadURL": ASSET_ROOT + ipa.name,
    }
    log(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def command_verify_release(args: argparse.Namespace) -> dict:
    build = int(args.build)
    rel = release()
    ipa = asset_by_name(rel, f"Tongiva-iOS-v{build}.ipa")
    plist = asset_by_name(rel, f"Tongiva-iOS-v{build}.plist")
    feed = asset_by_name(rel, "ios-update.json")
    for name, asset in (("IPA", ipa), ("plist", plist), ("feed", feed)):
        if not asset:
            raise PipelineError(f"release is missing {name}")
    with tempfile.TemporaryDirectory(prefix="tongiva-release-") as tmp:
        root = Path(tmp)
        ipa_path = root / ipa["name"]
        actual = download_public(ipa["browser_download_url"], ipa_path,
                                 expected_size=int(ipa["size"]))
        if args.sha256 and actual != args.sha256.lower():
            raise PipelineError("downloaded IPA sha256 does not match the local build")
        plist_path = root / plist["name"]
        download_public(plist["browser_download_url"], plist_path, expected_size=int(plist["size"]))
        feed_path = root / "ios-update.json"
        download_public(feed["browser_download_url"], feed_path)
        feed_value = json.loads(feed_path.read_text())
        if feed_value.get("build") != build:
            raise PipelineError("release feed build mismatch")
        if feed_value.get("sha256") != actual:
            raise PipelineError("release feed sha256 mismatch")
        if feed_value.get("manifestSHA256") != sha256_file(plist_path):
            raise PipelineError("release feed plist sha256 mismatch")
        profile = profile_dict(Path(args.profile))
        validate_profile(profile)
        expected = plistlib.loads(Path(args.entitlements).read_bytes())
        extract_ipa(ipa_path, root / "unpacked")
        app = single_app(root / "unpacked")
        verified = verify_app(app, profile, expected, build)
        verified.update({
            "ipaAssetId": ipa["id"],
            "ipaSize": ipa_path.stat().st_size,
            "ipaSHA256": actual,
            "plistAssetId": plist["id"],
            "plistSHA256": sha256_file(plist_path),
            "feedAssetId": feed["id"],
            "feedJSON": feed_value,
        })
    log(json.dumps(verified, ensure_ascii=False, indent=2))
    return verified


def command_next_build(args: argparse.Namespace) -> int:
    rel = release()
    builds = []
    for asset in rel["assets"]:
        match = re.fullmatch(r"Tongiva-iOS-v(\d+)\.ipa", asset.get("name", ""))
        if match:
            builds.append(int(match.group(1)))
    feed = asset_by_name(rel, "ios-update.json")
    if feed:
        try:
            with tempfile.TemporaryDirectory(prefix="tongiva-feed-") as tmp:
                target = Path(tmp) / "ios-update.json"
                download_public(feed["browser_download_url"], target)
                builds.append(int(json.loads(target.read_text()).get("build", 0)))
        except Exception:  # noqa: BLE001
            pass
    value = max(builds, default=0) + 1
    print(value)
    return value


def command_assets(args: argparse.Namespace) -> dict:
    rel = release()
    value = {
        "release": {"id": rel["id"], "name": rel["name"], "tag": rel["tag_name"]},
        "assets": [
            {"id": a["id"], "name": a["name"], "size": a["size"], "digest": a.get("digest"),
             "state": a.get("state"), "url": a.get("browser_download_url")}
            for a in sorted(rel["assets"], key=lambda x: x["name"])
        ],
    }
    log(json.dumps(value, ensure_ascii=False, indent=2))
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("package", help="re-sign an IPA/app and produce IPA + plist + ios-update.json")
    p.add_argument("--source-ipa", type=Path)
    p.add_argument("--app", type=Path)
    p.add_argument("--profile", type=Path, required=True)
    p.add_argument("--entitlements", type=Path, required=True)
    p.add_argument("--build", type=int, required=True)
    p.add_argument("--notes", default="")
    p.add_argument("--notes-file", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.set_defaults(func=command_package)

    p = sub.add_parser("verify", help="verify a local IPA signature, profile and entitlements")
    p.add_argument("--ipa", type=Path, required=True)
    p.add_argument("--profile", type=Path, required=True)
    p.add_argument("--entitlements", type=Path, required=True)
    p.add_argument("--build", type=int, required=True)
    p.add_argument("--plist", type=Path)
    p.set_defaults(func=command_verify)

    p = sub.add_parser("download", help="download a release asset and verify its digest")
    p.add_argument("--asset", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--sha256", default="")
    p.set_defaults(func=command_download)

    p = sub.add_parser("publish", help="upload IPA/plist/feed to the ios-updates release")
    p.add_argument("--ipa", type=Path, required=True)
    p.add_argument("--plist", type=Path, required=True)
    p.add_argument("--json", type=Path, required=True)
    p.add_argument("--build", type=int, required=True)
    p.add_argument("--notes", default="")
    p.add_argument("--notes-file", type=Path)
    p.add_argument("--overwrite", action=argparse.BooleanOptionalAction, default=True)
    p.set_defaults(func=command_publish)

    p = sub.add_parser("verify-release", help="download and verify the published IPA/plist/feed")
    p.add_argument("--build", type=int, required=True)
    p.add_argument("--sha256", default="")
    p.add_argument("--profile", type=Path, required=True)
    p.add_argument("--entitlements", type=Path, required=True)
    p.set_defaults(func=command_verify_release)

    p = sub.add_parser("next-build", help="print max(existing IPA builds, feed build) + 1")
    p.set_defaults(func=command_next_build)

    p = sub.add_parser("assets", help="print release assets as JSON")
    p.set_defaults(func=command_assets)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        result = args.func(args)
    except PipelineError as error:
        log("ERROR: " + str(error))
        raise SystemExit(1)
    if isinstance(result, (dict, list)):
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()

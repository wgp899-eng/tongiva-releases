# iOS build/sign/publish (GitHub-hosted macOS)

`.github/workflows/ios-build.yml` builds or re-signs the iOS app on
`macos-latest`, signs it with the Ad Hoc profile `Tongiva Ad Hoc 6 Devices
20261101T025724Z`, and publishes to the `ios-updates` Release.

Workflow inputs:

- `mode=build`: `xcodebuild archive` + `xcodebuild -exportArchive` from the
  private source repository, then a custom `codesign` pass with
  `Signing/TongivaAdHoc.entitlements`.
- `mode=resign`: download an existing release IPA (default v176) and re-sign
  it. This is the fallback if a future Xcode on the runner cannot build the
  project.
- `publish=false` (default): upload IPA/plist/JSON as workflow artifacts.
- `publish=true`: upload to the `ios-updates` Release, then download the
  published IPA again and verify `codesign`, the profile, entitlements and
  sha256 end-to-end.

Secrets used by the workflow:

- `IOS_DISTRIBUTION_P12` — base64 PKCS#12 (pre-existing in this repository)
- `IOS_P12_PASSWORD` — PKCS#12 password (pre-existing)
- `IOS_PROVISIONING_PROFILE` — base64 Ad Hoc `.mobileprovision`
- `SOURCE_DEPLOY_KEY` — read-only deploy key for the private source repo

The source repo is private (`wgp899-eng/tongiva-ios-source`); the workflow
runs in this public release repository because that is where the signing
secrets and the free macOS runner are configured.

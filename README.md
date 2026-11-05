# tongiva-releases
Tongiva Windows and iOS installation packages and updates.

## iOS client source and signing

`ios-client-source.json` pins the current iOS client source archive, feature IPA,
release notes, and SHA-256 hashes. The v113 source includes Telegram translation
below both received and sent messages, current native iPad/account fixes, and the
LINE synchronization resources already released in v112.

The matching `Tongiva-iOS-source-v113.zip` on the `ios-updates` Release contains
the Swift project, Telegram Web source, licenses, and prebuilt web resources. It
excludes local credentials, profiles, user settings, dependencies, and caches.
The feature IPA is built from that source and exported for distribution. The
Actions runner downloads and verifies the source archive and checks that its
configured web resources match the IPA before signing.

To publish the configured feature package, run **iOS automatic device signing**
on `main` with **use_configured_source** enabled and leave the explicit source
fields empty. The existing Apple signing and distribution secrets remain in
GitHub Secrets. Signing runs on GitHub's `macos-26` runner; this Mac is not needed
after the source assets have been uploaded.

Scheduled runs keep **use_configured_source** disabled and only re-sign when
registered devices change. They use the latest published complete IPA and verify
it against the configured source resources, preventing a return to an older
client. A feature publication always selects a build greater than the current
release, source build, and existing versioned packages. Windows assets and the
repository's Latest release are independent of the iOS channel.

For a later feature update, upload a new versioned source ZIP and IPA, update
`ios-client-source.json` with their hashes and matching resource/source hashes,
then run the workflow. Keep old packages and update manifests for existing users.

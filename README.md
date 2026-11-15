# tongiva-releases

Tongiva Windows and iOS installation packages and updates.

## iOS source v143

This source includes foreground, per-request consent for location sharing, native full iOS/iPadOS version reporting, and timeout/retry recovery for the workbench heartbeat. The existing multi-account message inbox, unread totals and native LINE text selection remain included.

Location collection starts only after explicit consent for the current request and stops when the app enters the background or the user logs out. Physical-device GPS, real customer sessions and in-place installation still require acceptance testing.

`ios-client-source.json` binds the complete source ZIP, feature-base IPA, release notes, packaged-resource digests and source-file digests. Signing credentials, provisioning profiles and private configuration are excluded from the source ZIP.

Run **iOS automatic device signing** on `main` with **use_configured_source** enabled and explicit source fields empty. The existing macOS runner and GitHub Secrets supply the distribution identity and restricted signing bridge. The workflow verifies the source and resources, preserves production APNs, signs for registered devices, publishes the IPA and installation manifest, then refreshes the distribution server.

Subsequent scheduled signing retains this source binding. Historical assets remain available; the iOS channel does not replace the Windows Latest release.

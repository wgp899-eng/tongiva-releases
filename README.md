# tongiva-releases

Tongiva Windows and iOS installation packages and updates.

## iOS source v123: real-device test

Published at the user's request for real-device testing. The LINE badge module reads authoritative duplicate metadata from each dialog where the server supplies it and retains the friends/new-contacts fallback for older servers. It handles phone row wrappers, account scope, refreshes and badge removal. The six reported customer cases remain unmatched in backend evidence; this release does not claim they are fixed. No production backend deployment is included.

`ios-client-source.json` pins `Tongiva-iOS-source-v123.zip`, the source IPA, notes and SHA-256 hashes. The source archive contains the Swift project, Telegram Web source, licenses, tests and bundled resources. Credentials, profiles, customer spreadsheets and debugging captures are excluded.

Run **iOS automatic device signing** on `main` with **use_configured_source** enabled and the explicit source fields empty. The existing signing bridge supplies the registered-device profile; the macOS runner verifies the source archive and IPA resources before re-signing and publishing the complete package, then refreshes the distribution server. Signing secrets and production APNs capability remain in the existing configuration.

Scheduled runs only re-sign when registered devices change, using the latest published full IPA and verifying it against the pinned resource hashes. Source updates use new versioned ZIP/IPA assets and a new configuration; old packages and manifests are retained. The iOS channel does not change the Windows Latest release.

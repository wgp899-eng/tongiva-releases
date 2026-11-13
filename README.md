# tongiva-releases

Tongiva Windows and iOS installation packages and updates.

## iOS source v137: LINE text selection and copy

In LINE chats, long-press a message and choose Copy to open a read-only text selection window containing the original and the currently displayed translation. Select either language, a substring, or both paragraphs, then copy the selection. Select All remains available. Clipboard failures preserve the selection for retry; message refreshes preserve the selection snapshot and composer draft. Existing message actions remain available.

The source preserves the v135 source / v136 release features, including LINE QR login retries and device egress. WebKit and Chrome browser checks cover original and translated text, cross-paragraph ranges, multiline text and emoji, clipboard fallback and retry, refreshes and drafts, media-only messages, escaping, reply actions, hold and scroll cancellation, navigation, and phone/tablet layouts. Customer real-device acceptance is still required.

`ios-client-source.json` pins `Tongiva-iOS-source-v137.zip`, `Tongiva-iOS-source-v137.ipa`, release notes, and SHA-256 hashes for packaged resources and source files, including the LINE copy implementation and its browser tests. The archive includes the Swift/Xcode project, Telegram Web source, bundled resources, licenses and tests. Signing credentials, provisioning profiles and customer data are excluded from the source archive.

Run **iOS automatic device signing** on `main` with **use_configured_source** enabled and explicit source fields empty. The existing restricted signing bridge supplies the registered-device profile. The macOS runner verifies the source archive and IPA resources, re-signs with the existing distribution identity while preserving production APNs, publishes the complete package and installation manifest, and refreshes the distribution server.

Scheduled device signing continues to verify and retain these resource hashes. Historical assets remain available. This iOS channel does not change the Windows Latest release.

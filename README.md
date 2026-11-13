# tongiva-releases

Tongiva Windows and iOS installation packages and updates.

## iOS source v139: LINE text selection and copy

In LINE chats, the existing long-press Reply / Copy / Share / Unsend menu stays available. Choosing Copy enables native text selection directly in the original message bubble, starting with the original or displayed translation according to where the user long-pressed. Use iOS selection handles and the system Copy menu to select and copy text. There is no separate text dialog. During selection, the old message menu cannot intercept the gesture. Copying or touching outside ends selection and restores the original message actions.

Polling keeps the selected paragraph mounted and retains the selected range and composer draft. Recalled, edited, deleted or switched messages end selection. The native WKWebView keeps multi-tap text selection recognizers enabled while viewport and zoom-scale limits continue to lock page zoom.

WebKit and Chrome regression checks passed. A dedicated iPhone iOS 27 simulator fixture used the production WebView class and message scripts to verify original/translation selection handles, separation from the old message menu, and actual system clipboard copy of the selected Chinese substring “谢谢”. Customer real-device acceptance remains required.

The source preserves the v135 source / v136 release features, including LINE QR login retries and device egress. WebKit and Chrome browser checks cover original and translated text, cross-paragraph ranges, multiline text and emoji, clipboard fallback and retry, refreshes and drafts, media-only messages, escaping, reply actions, hold and scroll cancellation, navigation, and phone/tablet layouts. Customer real-device acceptance is still required.

`ios-client-source.json` pins `Tongiva-iOS-source-v139.zip`, `Tongiva-iOS-source-v139.ipa`, release notes, and SHA-256 hashes for packaged resources and source files, including the LINE copy implementation and its browser tests. The archive includes the Swift/Xcode project, Telegram Web source, bundled resources, licenses and tests. Signing credentials, provisioning profiles and customer data are excluded from the source archive.

Run **iOS automatic device signing** on `main` with **use_configured_source** enabled and explicit source fields empty. The existing restricted signing bridge supplies the registered-device profile. The macOS runner verifies the source archive and IPA resources, re-signs with the existing distribution identity while preserving production APNs, publishes the complete package and installation manifest, and refreshes the distribution server.

Scheduled device signing continues to verify and retain these resource hashes. Historical assets remain available. This iOS channel does not change the Windows Latest release.

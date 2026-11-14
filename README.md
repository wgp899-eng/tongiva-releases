# tongiva-releases

Tongiva Windows and iOS installation packages and updates.

## iOS source v141: multi-account message inbox

The message list and chat header offer a shared inbox for unread conversations across signed-in accounts. Activation-code badges total unread messages for all accounts under that code. The inbox groups customer previews by activation and account, labels the sending platform/account, and opens the selected customer directly in the correct account. Returning restores the original conversation and draft.

Contextual banners, the capped-height inbox, native momentum scrolling and conversation transitions use composited motion and respect Reduce Motion. A slow request retains the original chat and inbox until the destination is ready; failures can be retried, closing cancels late navigation, and duplicate taps cannot start duplicate switches. Pointer Events track scrolling without interfering with WKWebView touch scrolling. The existing LINE native text selection and copy behavior remains included.

Chrome and WebKit checks passed for phone/tablet layouts, slow and failed requests, cancellation, direct routing, drafts, scrolling DOM retention, unread totals, activation isolation, Reduce Motion and the native Telegram bridge. The production WebView class and bundled resources were exercised with local data in an iPhone 17 Pro Max / iOS 27 simulator, including scrolling to the twentieth customer, opening that customer's B-account chat and returning to the A-account draft. Real customer accounts and physical devices still require acceptance testing.

`ios-client-source.json` binds the complete `Tongiva-iOS-source-v141.zip`, feature base `Tongiva-iOS-source-v141.ipa`, release notes, packaged-resource digests and source-file digests. Source archives exclude signing credentials, provisioning profiles and customer data.

Run **iOS automatic device signing** on `main` with **use_configured_source** enabled and explicit source fields empty. The existing restricted signing bridge provides the registered-device profile; the macOS runner verifies source and package contents, signs with the existing distribution identity while preserving production APNs, publishes the full IPA and installation manifest, and refreshes the distribution server.

Subsequent scheduled device signing verifies and retains this source binding. Historical iOS assets remain available. This channel does not replace the Windows Latest release.

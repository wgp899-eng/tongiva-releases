# tongiva-releases

Tongiva Windows and iOS installation packages and updates.

## Current iOS feature source: v145

The current source removes the application confirmation before location sharing and uses iOS system location authorization directly. The system asks when authorization is undetermined; existing authorization is respected. Denied, restricted and reduced-accuracy states remain enforced. Location is requested only for an authenticated, expiring foreground request, and stops when the app backgrounds or the user logs out. Permission descriptions disclose sending the single location, time and accuracy to the developer console.

Native full iOS/iPadOS version reporting, heartbeat timeout recovery, multi-account message inbox, unread totals, LINE text selection, account isolation and existing features remain included.

`ios-client-source.json` binds the complete source ZIP and feature-base IPA, release notes, packaged-resource digests and source-file digests. The generated binding is published separately from the ZIP to avoid a self-referential archive hash. Signing credentials and provisioning profiles are excluded from the source ZIP.

Run **iOS automatic device signing** on `main`, enable **use_configured_source**, and leave explicit source fields empty. The existing macOS runner and GitHub Secrets supply the distribution identity and restricted signing bridge. The workflow verifies the source and resources, preserves production APNs, signs for all registered devices, publishes the IPA and installation manifest, and refreshes the distribution server. The final release build is higher than the feature source build.

Subsequent automatic signing retains the current source binding. The iOS channel does not replace the Windows Latest release. Physical-device GPS and in-place installation require acceptance testing.

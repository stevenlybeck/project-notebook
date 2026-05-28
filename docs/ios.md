# Project Notebook — iOS App

The iOS app is the primary artifact source: a host app plus a Share
Extension that lets you send photos, videos, audio, and files to a
registered project from any app's share sheet. It POSTs to the hub's
`/api/ingest` endpoint (see [architecture.md](architecture.md)).

## Targets

| Target | Bundle ID | Role |
| ------ | --------- | ---- |
| `ProjectNotebook` | `com.projectnotebook.ProjectNotebook` | Host app — pairing/config UI, upload tracking |
| `ShareExtension` | `com.projectnotebook.ProjectNotebook.ShareExtension` | Share-sheet extension that uploads to the hub |

- **Deployment target:** iOS 16.0
- **Device family:** iPhone only (`TARGETED_DEVICE_FAMILY = 1`). iPad was
  dropped to avoid the iPad multitasking requirements (all-orientations,
  launch storyboard). Re-add by restoring `"1,2"` if iPad is ever wanted.
- **Development team:** `LSHKSFHL5R` (set on both targets).

## Versioning

Single source of truth is the build settings; the Info.plists reference
them via variable substitution:

- `CFBundleShortVersionString` = `$(MARKETING_VERSION)` — user-visible
  version (e.g. `1.0`). Bump for meaningful releases; a change triggers a
  fresh TestFlight Beta App Review.
- `CFBundleVersion` = `$(CURRENT_PROJECT_VERSION)` — build number. **Must
  be unique per upload within a marketing version** or App Store Connect
  rejects it. Bump on every upload.

Both targets must carry the same `MARKETING_VERSION` and
`CURRENT_PROJECT_VERSION` (App Store enforces extension == host app).

Bump in Xcode (Target → General → Identity) or in `project.pbxproj`. A
future option to auto-bump the build number (timestamp or git commit
count via `agvtool`) is noted in [PLAN.md](../PLAN.md).

## Naming

- **App Store listing name:** "Project Notebook" (set in App Store Connect).
- **Home-screen label** (`CFBundleDisplayName`): "Notebook" — shortened
  because iOS truncates home-screen labels around 11–12 characters.
- **Bundle name** (`CFBundleName`): `ProjectNotebook` — the short internal
  name; not normally user-visible.

## App icon

- Lives in `ProjectNotebook/Assets.xcassets/AppIcon.appiconset/`.
- **Single-size** catalog: one 1024×1024 source (`icon-1024.png`); Xcode
  generates all device sizes at build time.
- The source has **no alpha channel** (App Store rejects alpha on the
  marketing icon) and is full-bleed with no pre-applied rounded corners or
  shadow (iOS applies its own mask).
- Compiled into the bundle via the target's **Copy Bundle Resources** build
  phase; `CFBundleIconName = AppIcon` and the build setting
  `ASSETCATALOG_COMPILER_APPICON_NAME = AppIcon` point at it.

## Local network access

The app talks to the hub over the LAN, so it declares:

- `NSAppTransportSecurity → NSAllowsLocalNetworking = true` (allows
  plaintext HTTP to local addresses).
- `NSLocalNetworkUsageDescription` — the permission-prompt string. iOS
  shows a Local Network prompt on first access; if the user denies it, the
  share extension silently fails to reach the hub. Tell testers to allow it.

## Share Extension

`NSExtensionActivationRule` declares what the extension accepts (a
dictionary, not the wildcard `TRUEPREDICATE`, which the App Store rejects):

| Content | Max count |
| ------- | --------- |
| Images  | 20 |
| Movies  | 5  |
| Files   | 10 (covers audio + generic data) |

`ShareViewController.swift` handles `movie`, `image`, `audio`, and `data`
UTTypes. If audio sharing doesn't trigger the extension, add
`NSExtensionActivationSupportsAttachmentsWithMaxCount`.

## Export compliance

`ITSAppUsesNonExemptEncryption = NO` is set in both Info.plists. The app
uses only Apple-provided OS encryption (URLSession, Keychain) and
implements no custom crypto, so it's exempt. This key makes App Store
Connect skip the encryption question on every upload.

## Distribution (TestFlight)

1. **Product → Archive** in Xcode.
2. **Distribute App → App Store Connect → Upload**.
3. Wait for processing in App Store Connect (5–30 min).
4. Build appears in TestFlight. Internal testers (App Store Connect team
   members) get it immediately; external testers (email-only, up to 10k)
   require a one-time Beta App Review per marketing version.

Remember to bump `CURRENT_PROJECT_VERSION` before each archive.

## Known quirks

- **Home-screen label cache:** after a `CFBundleDisplayName` change, the
  home-screen label can stay stale even though the bundle is correct and
  TestFlight shows the new name. Springboard caches it. Restart the phone
  (or delete → restart → reinstall) to refresh. Not a project bug.

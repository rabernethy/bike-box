# Code-signing the installers

The release build (`.github/workflows/build.yml`) will **sign and notarise**
the macOS and Windows installers automatically **once you add the signing
secrets below**. Until then the steps are skipped and the installers ship
unsigned (users see a Gatekeeper / SmartScreen warning they must click past).

Everything here needs certificates that only you can obtain — Anthropic/Claude
cannot create them. Add them under **GitHub → repo → Settings → Secrets and
variables → Actions → New repository secret**.

## macOS (Gatekeeper / notarisation)
Requires an **Apple Developer Program** membership (US$99/yr).

1. In Apple Developer, create a **Developer ID Application** certificate; export
   it from Keychain as a `.p12` with a password.
2. Base64-encode it: `base64 -i DeveloperID.p12 | pbcopy`.
3. Create an **app-specific password** for your Apple ID (appleid.apple.com) for
   notarytool, and note your **Team ID**.

Secrets:
| Secret | Value |
|---|---|
| `MACOS_CERT_P12` | base64 of the `.p12` |
| `MACOS_CERT_PASSWORD` | the `.p12` export password |
| `MACOS_SIGN_IDENTITY` | e.g. `Developer ID Application: Your Name (TEAMID)` |
| `MACOS_NOTARY_APPLE_ID` | your Apple ID email |
| `MACOS_NOTARY_TEAM_ID` | your 10-char Team ID |
| `MACOS_NOTARY_PASSWORD` | the app-specific password |

## Windows (SmartScreen)
Requires a **code-signing certificate** (OV ~US$200/yr, or EV). Export as `.pfx`.

1. Base64-encode: `base64 -w0 cert.pfx` (or `certutil -encode`).

Secrets:
| Secret | Value |
|---|---|
| `WINDOWS_CERT_PFX` | base64 of the `.pfx` |
| `WINDOWS_CERT_PASSWORD` | the `.pfx` password |

## Notes
- The workflow gates each signing step on its secret being present, so adding
  only macOS (or only Windows) secrets signs just that platform.
- A brand-new OV/EV Windows cert still builds SmartScreen reputation over time;
  EV certs start trusted.
- Nothing in these secrets is printed in the build logs.

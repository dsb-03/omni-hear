# omnihear APT repository — setup guide

## 1. Generate your signing key (do this locally, never share the private key)

```bash
gpg --full-generate-key
# Choose RSA and RSA, 4096 bits, key does not expire (or set a long expiry)
# Use a real name/email you control, and set a strong passphrase
```

Find your key ID:
```bash
gpg --list-secret-keys --keyid-format=long
# look for the line: sec   rsa4096/ABCD1234EFGH5678 ...
# ABCD1234EFGH5678 is your key ID. Your email also works as GPG_KEY_ID.
```

## 2. First local publish (manual, to get things running)

```bash
./build-deb.sh 1.0.0
GPG_KEY_ID=you@example.com ./scripts/update-apt-repo.sh omnihear_1.0.0_amd64.deb
git add docs/
git commit -m "Publish omnihear 1.0.0"
git push
```

## 3. Enable GitHub Pages

Repo Settings → Pages → Source: **Deploy from a branch** → Branch: `main`, folder: `/docs`.

Your repo will be served at `https://dsb-03.github.io/omni-hear/`.

## 4. Client machine setup (do this once per machine)

```bash
# Add your public signing key
curl -fsSL https://dsb-03.github.io/omni-hear/pubkey.gpg | sudo gpg --dearmor -o /usr/share/keyrings/omnihear.gpg

# Add the repo source
echo "deb [signed-by=/usr/share/keyrings/omnihear.gpg] https://dsb-03.github.io/omni-hear/ stable main" \
  | sudo tee /etc/apt/sources.list.d/omnihear.list

sudo apt update
sudo apt install omnihear
```

From then on, updates are just:
```bash
sudo apt update && sudo apt upgrade
```

## 5. Automating future releases with GitHub Actions

The included `.github/workflows/release.yml` builds and publishes automatically whenever
you push a version tag like `v1.1.0`:

```bash
git tag v1.1.0
git push origin v1.1.0
```

This requires three repo secrets (Settings → Secrets and variables → Actions):

| Secret | Value |
|---|---|
| `GPG_PRIVATE_KEY` | `gpg --export-secret-keys --armor you@example.com \| base64 -w0` |
| `GPG_KEY_ID` | your key ID or email, e.g. `you@example.com` |
| `GPG_PASSPHRASE` | the passphrase you set in step 1 |

**Security note:** these secrets let CI sign packages that your client machines will trust
and auto-install. Treat them like production credentials — GitHub secrets are encrypted
at rest and masked in logs, but only add this automation if you're comfortable with CI
holding signing capability. For a single-user/small-scale setup, doing releases manually
(step 2) with the key only ever living on your own machine is the more conservative option.

## 6. macOS releases (DMG + Homebrew Cask)

The same tag push (`v1.4.0`) that builds the `.deb` and Windows installer also
runs the **`build-macos`** job on an Apple Silicon runner: it builds
`Omnihear.app` with PyInstaller, packages it into
`omnihear-<version>-arm64.dmg`, and attaches the DMG to the GitHub Release.
**No extra secrets are needed for the unsigned DMG** — it works out of the box
(users clear Gatekeeper once; see the README's macOS section).

### Homebrew Cask (optional, one-time setup)

To let users `brew install --cask`:

1. Create a **separate** public repo named `homebrew-omnihear` (Homebrew taps
   must be named `homebrew-<tap>`). It can start empty.
2. Create a PAT with push access to that repo and add it to **this** repo as a
   secret; add the tap repo path as a repo **variable**:

   | Kind | Name | Value |
   |---|---|---|
   | Secret | `HOMEBREW_TAP_TOKEN` | a PAT (fine-grained: Contents read/write on `homebrew-omnihear`) |
   | Variable | `HOMEBREW_TAP_REPO` | `your-user/homebrew-omnihear` |

3. On the next release, the `build-macos` job runs `macos/update-cask.sh`,
   which computes the DMG's `sha256` and pushes a generated
   `Casks/omnihear.rb` to the tap. Users then:

   ```bash
   brew tap your-user/omnihear      # or brew install --cask directly
   brew install --cask your-user/omnihear/omnihear
   ```

   Without `HOMEBREW_TAP_TOKEN`, the cask step is skipped and only the DMG
   ships.

### Code signing + notarization (optional — removes the Gatekeeper prompt)

Add these secrets (from an Apple Developer account, $99/yr) to enable signing;
the `sign.sh` steps are no-ops until they exist, so nothing else changes:

| Secret | Value |
|---|---|
| `APPLE_SIGN_IDENTITY` | `Developer ID Application: Your Name (TEAMID)` |
| `APPLE_TEAM_ID` | your 10-char Team ID |
| `APPLE_ID` | your Apple account email |
| `APPLE_APP_PASSWORD` | an app-specific password for notarization |

You'll also need to import the `Developer ID Application` certificate into the
runner's keychain (a standard `apple-actions/import-codesign-certs` step) —
add that to the `build-macos` job when you switch signing on. Once notarized,
the app opens with no warning and Accessibility/Input-Monitoring grants persist
across updates.

## Editing the app for a new version

1. Edit files under `src/` (`omnihear.py`, `requirements.txt`, etc.)
2. Bump the version and build: `./build-deb.sh 1.2.0`
3. Publish via step 2 (manual) or by tagging a release (step 5, automated)

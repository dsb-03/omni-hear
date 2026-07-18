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

## Editing the app for a new version

1. Edit files under `src/` (`omnihear.py`, `requirements.txt`, etc.)
2. Bump the version and build: `./build-deb.sh 1.2.0`
3. Publish via step 2 (manual) or by tagging a release (step 5, automated)

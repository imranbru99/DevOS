# DevOS update signing keys

Pinned public key (shipped in the image):

- `/usr/local/share/devos/keys/update-pubkey.pub`

Optional site override:

- `/etc/devos/update-pubkey.pub`

When a pinned key is present, `devos-update.tar.gz.sig` on the GitHub release is
**required**. Verification uses `minisign` if installed, otherwise
`ssh-keygen -Y verify` (principal `devos-update`, namespace `file`).

## Publishers

1. Keep the private OpenSSH ed25519 key offline (repo path `secrets/` is gitignored).
2. Store it in GitHub Actions as secret `DEVOS_UPDATE_SIGN_KEY_B64`
   (`base64 -w0 secrets/devos-update-ed25519`).
3. Tag `v*` or run the `release-update` workflow — it signs and uploads `.sig`
   next to `.sha256`.

Local sign:

```sh
python3 tools/package-update.py v26.04.1 --sign-key secrets/devos-update-ed25519 --require-signature
```

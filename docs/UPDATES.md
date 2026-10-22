# DevOS updates

On images that include the updater, get the latest stable DevOS release with:

```sh
devos update
```

Enter your administrator password when asked. The updater uses published
GitHub releases from `imranbru99/DevOS`, checks the bundle and file checksums,
and restores changed files if installation fails. It installs missing Kids Mode
desktop libraries and refreshes an already-enabled Modesty Filter while preserving
its mode. Reopen DevOS apps and browsers afterward; sign out and back in to load
new desktop shortcuts.
It does not install an arbitrary branch or silently change the Ubuntu base.

```sh
devos update --check                # Check without making changes
devos update --version v26.04.1     # Choose an existing stable release tag
devos update --os-upgrade          # Separate, interactive Ubuntu LTS upgrade
devos update --rollback            # Restore files from the previous component update
```

`devos-update` accepts the same options. `devos updates now` continues to handle
Ubuntu security updates and Flatpak apps.

The version example above is a tag format, not a claim that the release exists.
Until maintainers publish a bundle, the updater reports that no release is available.

## Existing DevOS 24.04 installations

If `devos update` is not yet installed, bootstrap it with one command:

```sh
bash <(curl -fsSL https://raw.githubusercontent.com/imranbru99/DevOS/main/tools/install-update.sh)
```

Add `--version TAG` after the closing parenthesis to choose a published version.
The bootstrap downloads the updater over HTTPS; the updater verifies the release
bundle and prompts for administrator access before installing.


From an updated source checkout, start the Ubuntu 26.04 upgrade in a terminal:

```sh
sudo bash build/includes.chroot/usr/local/sbin/devos-upgrade-os
```

The helper checks the current base, package health, free space, and power;
backs up APT configuration and the package list; creates a Btrfs snapshot when
applicable; installs current updates; then starts Ubuntu's official release
upgrader. Keep a separate backup of personal files. If current updates require
a restart, restart and run the command again. It never forces a development
release or replaces APT suite names by hand. Third-party repositories may need
to be re-enabled after their vendors support the new release.

The installed system still requires review and restart in a real terminal.
An ISO build does not upgrade the PC running the build.

## Publishing updates

Push a stable `v*` tag after testing the release. The `release-update` GitHub
Actions workflow builds and uploads `devos-update.tar.gz` and its `.sha256`
file. Existing tags can be selected through the workflow's manual trigger.
Published assets are not overwritten. The update bundle includes DevOS
components, launchers, and the Kids Mode desktop shortcut. It excludes user data,
AI language-model weights, and APT configuration. Local body-detection assets are
included with the browser filter.
The manifest records the compatible Ubuntu bases. Component releases currently
support 24.04 and 26.04, so users can update DevOS apps before upgrading Ubuntu.
An incompatible base is rejected and requires a separate supported OS upgrade.

For a local package check:

```sh
python3 -m unittest discover -s tests/unit -p test_updater.py
python3 tools/package-update.py v26.04.1 --output out/update
```

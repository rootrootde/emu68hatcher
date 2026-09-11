# Update manifest

**manifest-source.json** contains package download replacements. It cannot change package
installation rules or files bundled with the application.

After changing a package entry, run the **Publish update manifest** workflow. It reads the latest
published application release, adds installer URLs and SHA-256 hashes, signs the result, and
publishes **manifest.json** on the **updates** branch.

## Package checks

**check-package-downloads.py** downloads every remote package using the replacements from
**manifest-source.json**, compares its MD5 checksum, and compares pinned GitHub tags with the
latest release. The weekly **Check package downloads** workflow opens or updates one issue when it
finds a changed file, a newer release, a missing checksum, or a broken link. It closes the issue
after the catalogue passes again.

A fixed web URL can only be checked for reachability and changed content. The checker cannot find
a new release published under a different URL. Set **download.check_latest_release** to false only
for a GitHub package that intentionally stays on an older release.

The workflow needs the PEM contents of **hatcher_data/update-signing-key.pem** in the repository
secret **UPDATE_MANIFEST_PRIVATE_KEY**. That key is local and ignored by Git. Losing it requires a
new application release with a new public key.

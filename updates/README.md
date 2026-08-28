# Update manifest

**manifest-source.json** contains package download replacements. It cannot change package
installation rules or files bundled with the application.

After changing a package entry, run the **Publish update manifest** workflow. It reads the latest
published application release, adds installer URLs and SHA-256 hashes, signs the result, and
publishes **manifest.json** on the **updates** branch.

The workflow needs the PEM contents of **hatcher_data/update-signing-key.pem** in the repository
secret **UPDATE_MANIFEST_PRIVATE_KEY**. That key is local and ignored by Git. Losing it requires a
new application release with a new public key.

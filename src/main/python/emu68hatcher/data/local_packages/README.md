# Local Packages

This directory contains bundled local packages that cannot be downloaded from
the internet due to licensing restrictions.

## Required Packages

### Roadshow-Demo-1.15.lha
TCP/IP networking stack for Amiga. This is required for network functionality.

**Note:** This is the DEMO version, not the SDK. The demo is what users need
for networking; the SDK is for developers.

**How to obtain:**
- Original CD distributions
- Amiga Forever bundles
- Contact the author (Magnus Holmgren)

**Installation:**
Place `Roadshow-Demo-1.15.lha` in this directory.

## Package Status

The build will check for these packages and warn if they're missing.
Network functionality will be disabled if Roadshow is not available.

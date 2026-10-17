#!/usr/bin/env python3
"""
Pack the DevOS Modesty filter extension into a signed CRX3 + update manifest.

    tools/pack-modesty-extension.py [--out DIR] [--codebase-dir /usr/share/devos/modesty]

Signing key: components/modesty/key.pem (created on first run if missing).
It is the signing key of a LOCAL-ONLY extension: it only pins the extension
ID used in the force-install policy; nothing signed with it is published.
Uses the Python `cryptography` package if present, otherwise the openssl CLI.
Prints the extension ID.
"""

import argparse
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODESTY = os.path.join(REPO, "components", "modesty")
sys.path.insert(0, MODESTY)

import crx3  # noqa: E402
import modesty  # noqa: E402

KEY_COMMENT = ("DevOS Modesty filter CRX signing key. LOCAL-ONLY extension: this key only fixes the\n"
               "extension ID (it never signs anything published to a store). Not a secret in the\n"
               "usual sense; anyone with root on the PC can change browser policy anyway.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=os.path.join(MODESTY, "dist"))
    ap.add_argument("--codebase-dir", default="/" + modesty.INSTALL_DIR,
                    help="directory the CRX is installed to (used in the update manifest's file:// codebase)")
    ap.add_argument("--key", default=modesty.KEY_PATH)
    args = ap.parse_args()

    if not os.path.exists(args.key):
        crx3.generate_key(args.key, KEY_COMMENT)
        print("Generated new signing key: %s" % args.key)
    ext_id, version = modesty.pack(args.out, args.codebase_dir, key_path=args.key)
    crx_path = os.path.join(args.out, modesty.CRX_NAME)
    print("Extension ID: %s" % ext_id)
    print("Version:      %s" % version)
    print("CRX:          %s (%d bytes)" % (crx_path, os.path.getsize(crx_path)))
    print("Update XML:   %s" % os.path.join(args.out, modesty.UPDATE_XML))
    print("Signer:       %s" % ("cryptography" if crx3.HAVE_CRYPTOGRAPHY else "openssl CLI"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

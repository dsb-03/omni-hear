#!/bin/bash
# Rebuilds the .deb package.
# Usage: ./build-deb.sh 1.1.0
set -e

VERSION="${1:?Usage: ./build-deb.sh <version, e.g. 1.1.0>}"
PKG_DIR="omnihear_${VERSION}_amd64"

rm -rf "$PKG_DIR"
mkdir -p "$PKG_DIR/DEBIAN" "$PKG_DIR/opt/omnihear" "$PKG_DIR/usr/bin" \
         "$PKG_DIR/usr/lib/systemd/user"

# copy packaging metadata, substituting the version
sed "s/^Version:.*/Version: ${VERSION}/" DEBIAN-template/control > "$PKG_DIR/DEBIAN/control"
cp DEBIAN-template/postinst "$PKG_DIR/DEBIAN/postinst"
cp DEBIAN-template/postrm "$PKG_DIR/DEBIAN/postrm"

# copy app source (this is the part you edit for updates)
cp -r src/omnihear "$PKG_DIR/opt/omnihear/omnihear"
rm -rf "$PKG_DIR/opt/omnihear/omnihear/__pycache__"
cp src/requirements.txt "$PKG_DIR/opt/omnihear/"
cp src/omnihear-wrapper "$PKG_DIR/usr/bin/omnihear"
cp systemd/omnihear.service "$PKG_DIR/usr/lib/systemd/user/omnihear.service"

chmod 755 "$PKG_DIR/DEBIAN/postinst" "$PKG_DIR/DEBIAN/postrm" "$PKG_DIR/usr/bin/omnihear"
chmod 644 "$PKG_DIR/opt/omnihear/omnihear/"*.py "$PKG_DIR/opt/omnihear/requirements.txt" \
          "$PKG_DIR/usr/lib/systemd/user/omnihear.service"

dpkg-deb --build --root-owner-group "$PKG_DIR"
echo "Built ${PKG_DIR}.deb"

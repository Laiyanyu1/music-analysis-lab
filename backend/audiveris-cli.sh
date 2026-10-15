#!/bin/zsh
set -e
BASE_DIR="${0:A:h}"
APP_DIR="$BASE_DIR/vendor/audiveris-macos/Audiveris/Audiveris.app/Contents/app"
JAVA_BIN="$BASE_DIR/vendor/audiveris-macos/Audiveris/Audiveris.app/Contents/runtime/Contents/Home/bin/java"

exec "$JAVA_BIN" \
  -Djava.awt.headless=true \
  -Dfile.encoding=UTF-8 \
  -Xms512m -Xmx4G \
  --add-exports=java.desktop/sun.awt.image=ALL-UNNAMED \
  --enable-native-access=ALL-UNNAMED \
  -cp "$APP_DIR/*" Audiveris "$@"

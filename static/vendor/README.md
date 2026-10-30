# Vendored libraries

Self-hosted (no CDN requests), copied unmodified from npm:

- `qrcode.js`: [qrcode-generator](https://www.npmjs.com/package/qrcode-generator) 2.0.4 by Kazuhiko Arase, MIT licence (header in the file). Package checksum `sha512-mZSiP6RnbHl4xL2Ap5HfkjLnmxfKcPWpWe/c+5XxCuetEenqmNFf1FH/ftXPCtFG5/TDobjsjz6sSNL0Sr8Z9g==`.

Used to draw folded-note links as QR codes in the browser: the link carries the decryption key after `#`, so it must never be sent to a server to render.

| Encoding / corpus | Cases | Exact matches |
| --- | ---: | :---: |
| plain | 1 | ✓ |
| url-encoded | 1 | ✓ |
| url-all-bytes | 1 | ✓ |
| base64 offset 0 | 1 | ✓ |
| base64url offset 0 | 1 | ✓ |
| base64 offset 1 | 1 | ✓ |
| base64url offset 1 | 1 | ✓ |
| base64 offset 2 | 1 | ✓ |
| base64url offset 2 | 1 | ✓ |
| gzip | 1 | ✓ |
| multi-member gzip | 1 | ✓ |
| zstd | 1 | ✓ |
| multi-frame zstd | 1 | ✓ |
| zlib | 1 | ✓ |
| raw deflate (HTTP) | 1 | ✓ |
| zip | 1 | ✓ |
| tar | 1 | ✓ |
| zip-in-gzip | 1 | ✓ |
| base64(gzip) | 1 | ✓ |
| base64(zip) | 1 | ✓ |
| base64(zstd) | 1 | ✓ |
| url(gzip) | 1 | ✓ |
| gRPC gzip (embedded) | 1 | ✓ |
| gRPC gzip (header) | 1 | ✓ |
| gRPC zstd (embedded) | 1 | ✓ |
| gRPC zstd (header) | 1 | ✓ |
| brotli (HTTP) | 1 | ✓ |
| Connect brotli (header) | 1 | ✓ |
| stacked HTTP encodings | 1 | ✓ |
| hex lower | 1 | ✓ |
| hex upper | 1 | ✓ |
| UTF-16LE | 1 | ✓ |
| UTF-16BE | 1 | ✓ |
| JSON Unicode escapes | 1 | ✓ |
| websocket-split | 1 | ✓ |
| zip filename | 1 | ✓ |
| tar filename | 1 | ✓ |
| websocket every split | 19 | ✓ |
| websocket base64 long prefix | 72 | ✓ |
| base64 wrapped 64 columns | 128 | ✓ |
| base64 wrapped 76 columns | 152 | ✓ |
| JSON slash-escaped base64(gzip) | 1 | ✓ |
| JSON backslash escapes | 1 | ✓ |
| base64 after git diff indexes | 1 | ✓ |
| base64 after 64 ordinary runs | 1 | ✓ |
| gRPC-web-text plain | 1 | ✓ |
| gRPC-web-text gzip | 1 | ✓ |
| base64 after short runs | 1 | ✓ |
| negative empty HTTP bodies | 5 | ✓ |
| zip with binary percent sequences | 1 | ✓ |
| negative sniffed zlib (base64) | 1 | ✓ |
| negative sniffed zlib (percent) | 1 | ✓ |
| negative random bytes | 48 | ✓ |
| negative one-character mutations | 1400 | ✓ |
| negative other-run tokens | 35 | ✓ |

This deterministic offline corpus checks exact synthetic-token detection, not real-agent capture coverage. Expansion shares a 200 MiB output budget with four recursive levels, 4,096 archive members, 4,096 plausible base64 candidates and 64 embedded streams per blob; RPC envelopes also have a 4,096-frame limit. HTTP uploads retain at most 200 MiB of wire data. WebSocket reassembly retains only a token-sized outbound overlap per connection; compressed containers split beyond it and opaque application encryption remain unreadable. Independently base64-encoded application chunks (JSON arrays or separate WebSocket messages) are not joined. Unavailable codecs, damaged containers and exhausted decoding or capture limits are reported as uninspected; this table does not prove zero false positives outside the corpus.

Uninspected: decoding nesting limit reached

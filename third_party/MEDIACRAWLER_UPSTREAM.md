# MediaCrawler upstream record

- Upstream repository: NanmiCoder/MediaCrawler
- Import method: Git subtree with `--squash`
- Import directory: `third_party/MediaCrawler`
- Upstream branch: `main`
- Upstream commit: `071c8c0acaece3e82f2532cffb19faeddc9ec1c3`
- Import date (UTC): `2026-08-06`
- License: NON-COMMERCIAL LEARNING LICENSE 1.1

## Local enhancement boundary

Only the following enhancements are planned inside the vendored source:

1. Checkpoint and resumable collection
2. Incremental collection watermarks
3. Account and browser-profile abstraction
4. Signature-provider decoupling
5. Limited HomeFeed and hot-list discovery
6. Standardized platform risk-error output

AI scoring, event clustering, editorial drafting, provider routing and the
product UI remain in the main application and must not be implemented in
MediaCrawler.

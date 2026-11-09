# PhotoPrism Connector Verification Report

- M-Film revision / deployed version:
- PhotoPrism release/version:
- Access method: read-only bind mount / WebDAV / API original download:
- Auth scopes verified (do not include actual secrets):
- Tested at / test data:

| Operation | Expected result | Observed | Status |
|---|---|---|---|
| API authentication | list allowed instances | | NOT TESTED |
| Browse folders | directories shown | | NOT TESTED |
| Browse albums | manual albums shown | | NOT TESTED |
| Browse album photos | paginate / merged files | | NOT TESTED |
| Locate Nikon D5100 NEF | file-level RAW detected | | NOT TESTED |
| Locate CHDK DNG | file-level RAW detected | | NOT TESTED |
| Read source bytes | SHA-256 verified | | NOT TESTED |
| Render from PhotoPrism RAW | high-res JPEG generated | | NOT TESTED |
| Publish output folder | new JPEG indexed | | NOT TESTED |
| Create/choose manual album | destination UID valid | | NOT TESTED |
| Attach indexed photo to album | membership verified | | NOT TESTED |
| Error/offline / restart | automatic retry | | NOT TESTED |

## Environment-specific workarounds / API validation

## Blockers and recommended next step

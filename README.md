# STS2 CLab training

Private repository for audited Defect A10 cloud sampling and MiniMax-directed publishing.

## Current allocation

`defect-cloud-training-20260917a`: 24 predeclared fresh natural games, one worker, fixed Linux-validated 471-weight policy. This collects training data; it does not fit or deploy new weights. The current batch stops on completion. Local Windows training remains paused.

## Contents

- `batches/<batch>/games/*.zip`: immutable archives of completed games, including invalid/censored games when available; each ZIP has a SHA256 member manifest and original audit receipt.
- `snapshot.json`, `ARCHIVE_INDEX.json`, `REPORT.md`: progress and deterministic totals. MiniMax narrative is identified separately from verified counts.
- `PROTOCOL.json`, `model.json`: fixed sampling protocol and numeric policy. No game DLLs, accounts, API keys, SSH private keys, or raw DSH sessions are uploaded.
- `automation/`: the fixed adapter, contracts and current runner; these scripts are reference copies, not GitHub Actions.

## MiniMax responsibility

The existing MiniMax-M3 agent reads sanitized status and frozen completed-game counts, writes a Chinese report, and chooses `publish_snapshot`, `wait`, or `escalate`. A host adapter validates the exact snapshot ID and executes only the fixed archive/push operation. It cannot turn model output into shell commands, switch destinations, launch training, alter weights or delete originals. Unexpected responses or uncertain transactions stop for review.

Publishing is requested after roughly every four additional finished games and at completion. Raw in-progress games stay on the cloud host. Normal uploads use a repository-scoped SSH deploy key. Root filesystem certificate stores and proxy settings are unchanged.

## Limits and interpretation

Per file <45 MB; repository working tree plus local Git history <900 MB before push. Raw originals are retained on the cloud host. Completion/validity counts are not win counts. These samples do not establish a paired performance improvement or guaranteed third-act success.

## Network

Direct GitHub access and authenticated Git operations work on this host. Watt Toolkit officially provides Linux x64 builds; its current desktop client uses X11 and the accelerator entry is an IPC subprocess. No headless standalone accelerator setup was verified, so it is not enabled on this server. Sources: https://github.com/BeyondDimension/SteamTools/releases and https://github.com/BeyondDimension/SteamTools/blob/develop/src/BD.WTTS.Client.Avalonia.App/Program.cs .

# Lazer Config Linter (VS Code Extension)

Inline diagnostics for pyth-lazer governance proposal `after.json` files. Runs the Python config linter on save and surfaces all 26 lint rules as VS Code diagnostics.

## Install

1. Download the latest `lazer-config-linter-<version>.vsix` from the [GitHub release page](https://github.com/pyth-network/integration-benchmarking/releases?q=vscode-extension).
2. Install:
   - Command line: `code --install-extension lazer-config-linter-<version>.vsix`
   - Or in VS Code: `Extensions: Install from VSIX...` command palette action.

## Requirements

- Python 3.x on `PATH` (or set `lazerConfigLinter.pythonPath` to the interpreter).
- The `config_linter.py` source is auto-detected by walking up from the saved file. Override with `lazerConfigLinter.linterPath` for non-standard layouts.

## Activation

The extension activates on any JSON file but only processes saves of files matching `<date>-T<time>-<slug>/after.json` — the proposal-directory pattern used in `pyth-lazer-governance` and `pyth-lazer-staging-governance`. Saves of other JSON files are silently ignored.

## Configuration

| Setting                        | Default     | Description                                                    |
| ------------------------------ | ----------- | -------------------------------------------------------------- |
| `lazerConfigLinter.pythonPath` | `"python3"` | Python interpreter path.                                       |
| `lazerConfigLinter.linterPath` | `null`      | Explicit `config_linter.py` path. `null` triggers auto-detect. |
| `lazerConfigLinter.timeout`    | `5000`      | Subprocess kill timeout (ms).                                  |
| `lazerConfigLinter.lintOnSave` | `true`      | Master switch.                                                 |

## Behavior

On save of a proposal `after.json`, the extension:

1. Auto-detects the linter location (walks up looking for `tools/config-linter/config_linter.py`).
2. Detects sibling `before.json` (passed as `--baseline` if present, otherwise `--no-baseline`).
3. Spawns `python3 config_linter.py --config <file> ... --format json`.
4. Parses the linter's JSON output and shows each finding as an inline diagnostic anchored to the offending feed or publisher.

Failures (Python missing, linter missing, subprocess crash, timeout) appear as a single line-0 diagnostic — never silent.

# case-guide

Turns a case brief into a step-by-step implementation guide using Claude.

## Setup

```bash
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Usage

```bash
python case_guide.py T2611845
python case_guide.py T2611845 --skip-ado        # brief only, no live ADO
python case_guide.py T2611845 --show-prompt     # preview prompt, no call
python case_guide.py T2611845 --model opus      # use a different model
python case_guide.py T2611845 --no-open         # don't open in VS Code
python case_guide.py -h                         # all options
```

Requires:
- Brief from `case-brief` (reads `../case-brief/case-briefs/case-<code>.md`)
- Claude CLI (`claude` on PATH)
- `AZDO_PAT` env var (for Azure DevOps pull)

Output: `case-guides/case-<code>-for-dummies.md`

## Config

Edit `config.json` (optional) or use CLI flags. See `config.example.json`.

## Testing

```bash
python -m unittest discover -s tests -v   # 63 tests, mocked, no network
python case_guide.py T2611845 --show-prompt   # assembles the real prompt, no claude call
```

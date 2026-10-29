"""Export a sanitized publication snapshot without copying private Git history."""
import argparse
import ipaddress
import io
import json
from pathlib import Path
import re
from urllib.parse import parse_qsl, urlsplit
import zipfile


EVIDENCE_DIRS = ('desktop-results', 'mac-results', 'thinkpad-results',
                 'debianarze-results', 'm1-pro-results', 'xfs-results',
                 'xfs-pilot-results', 'mac-tuning-results')
PUBLIC_DOMAINS = {'github.com', 'raw.githubusercontent.com', 'docs.kernel.org',
                  'developer.apple.com', 'support.apple.com', 'pnpm.io',
                  'www.youtube.com', 'youtube.com', 'nodejs.org',
                  'registry.npmjs.org', 'chezmoi.io', 'www.chezmoi.io',
                  'mths.be', 'btrfs.readthedocs.io', 'btrfs.wiki.kernel.org'}
URL = re.compile(r'(?:https?|ssh|git|wss?)://[^\s<>"\x27]+')
TOKEN = re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16})\b')
ADDRESS = re.compile(r'\b[\w.-]+\.ts\.net\b|(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])')
SENSITIVE_KEY = re.compile(r'^(?:hostname|nodename|password|passwd|token|access_token|refresh_token|api_key|apikey|secret|authorization)$', re.I)


def private_url(value):
    try:
        url = urlsplit(value)
        keys = {k.lower() for k, _ in parse_qsl(url.query)}
        return (url.hostname not in PUBLIC_DOMAINS or url.username is not None
                or url.password is not None
                or any(re.search(r'token|secret|password|signature|api.?key|credential|authorization|^code$|^state$', k) for k in keys))
    except ValueError:
        return True


def sanitize_string(value):
    value = URL.sub(lambda m: '[REDACTED-URL]' if private_url(m[0]) else m[0], value)
    value = TOKEN.sub('[REDACTED-CREDENTIAL]', value)
    def address(match):
        if match[0].endswith('.ts.net'):
            return '[REDACTED-ADDRESS]'
        try:
            ipaddress.ip_address(match[0])
            return '[REDACTED-ADDRESS]'
        except ValueError:
            return match[0]
    return ADDRESS.sub(address, value)


def sanitize_text(text, is_json=False):
    if not is_json:
        return sanitize_string(text)
    original = json.loads(text)
    def walk(value):
        if isinstance(value, dict):
            return {k: '[REDACTED]' if SENSITIVE_KEY.fullmatch(k) else walk(v)
                    for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v) for v in value]
        return sanitize_string(value) if isinstance(value, str) else value
    sanitized = walk(original)
    return text if sanitized == original else json.dumps(sanitized, indent=2) + '\n'


def export(root, destination):
    root, destination = Path(root), Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    files = [p for p in root.iterdir() if p.is_file()
             and (p.suffix in ('.py', '.md', '.json', '.html', '.csv', '.txt') or p.name == '.gitignore')
             and 'manifest' not in p.name]
    for directory in EVIDENCE_DIRS:
        files.extend(p for p in (root / directory).rglob('*') if p.is_file())
    changed = []
    for path in sorted(files):
        if path.name.startswith('._') or '__pycache__' in path.parts or path.is_symlink():
            continue
        relative = path.relative_to(root)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        text = path.read_text()
        # Runner source is retained byte-for-byte; the final audit also checks it.
        sanitized = text if path.suffix == '.py' else sanitize_text(text, path.suffix == '.json')
        target.write_text(sanitized)
        if text != sanitized:
            changed.append(str(relative))
    audit = {'scope': 'Private/service URLs, network addresses, inventory hostnames and credentials.',
             'public_references_preserved': True, 'history': 'Fresh export; original Git history excluded.',
             'redacted_files': changed,
             'provenance': 'Original checksums in cleanup receipts describe the original evidence. Publication manifests describe sanitized files.'}
    (destination / 'publication-audit.json').write_text(json.dumps(audit, indent=2) + '\n')
    # Published evidence is tracked; local scratch/auth directories stay ignored.
    ignored = {d + '/' for d in EVIDENCE_DIRS} | {
        'benchmark-evidence.zip', 'xfs-experiment-evidence.zip', 'combined-evidence.zip',
        'mac-tuning-evidence.zip', 'comparison.html', 'comparison.json',
        'comparison-all.html', 'comparison-all.json'}
    ignore = destination / '.gitignore'
    ignore.write_text('\n'.join(line for line in ignore.read_text().splitlines() if line not in ignored)
                      + '\n._*\n.DS_Store\n')
    workflow = root / '.github/workflows/reports.yml'
    if workflow.exists():
        target = destination / '.github/workflows/reports.yml'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(workflow.read_bytes())
    return audit


def audit_snapshot(root):
    count = 0
    def check(name, data):
        nonlocal count
        count += 1
        if name.endswith('.zip'):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for member in archive.infolist():
                    if not member.is_dir():
                        check(name + '!' + member.filename, archive.read(member))
            return
        text = data.decode('utf-8')
        if 'PRIVATE ' + 'KEY-----' in text or sanitize_text(text, name.endswith('.json')) != text:
            # Report only paths, never the matching secret or private address.
            raise ValueError(f'Unsanitized publication file: {name}')
    for path in sorted(Path(root).rglob('*')):
        if not path.is_file() or '.git' in path.parts or '__pycache__' in path.parts:
            continue
        check(str(path.relative_to(root)), path.read_bytes())
    return count


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path, nargs='?')
    parser.add_argument('--audit', action='store_true', help='Audit this snapshot and every nested evidence ZIP')
    args = parser.parse_args()
    if args.audit:
        print(f'Audited {audit_snapshot(Path(__file__).resolve().parent)} files including nested ZIP contents.')
    elif args.destination:
        audit = export(Path(__file__).resolve().parent, args.destination)
        print(f"Exported sanitized snapshot; redacted {len(audit['redacted_files'])} files.")
    else:
        parser.error('Provide a destination or --audit')

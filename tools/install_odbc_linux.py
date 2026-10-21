"""Install a user-local Microsoft ODBC driver from a signed Debian repository.
No root, TLS bypass, or repository-file edits. Running accepts Microsoft's EULA.
Windows users must use Microsoft's official MSI instead (see README).
"""
import gzip
import hashlib
from pathlib import Path
import subprocess
import tempfile
import functools
from urllib.request import urlopen

BASE = 'https://packages.microsoft.com'
REPO = BASE + '/debian/13/prod'
ROOT = Path('/workspace/.etl-odbc')

def download(url):
    with urlopen(url, timeout=60) as response:
        return response.read()

def main():
    ROOT.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        temp = Path(temp)
        home = temp / 'gnupg'
        home.mkdir(mode=0o700)
        for name in ['microsoft.asc', 'microsoft-2025.asc']:
            key = temp / name
            key.write_bytes(download(BASE + '/keys/' + name))
            subprocess.run(['gpg', '--batch', '--homedir', str(home), '--import', str(key)], check=True, capture_output=True)
        signed = temp / 'Release.gpg'
        signed.write_bytes(download(REPO + '/dists/trixie/Release.gpg'))
        release = temp / 'Release'
        release.write_bytes(download(REPO + '/dists/trixie/Release'))
        subprocess.run(['gpg', '--batch', '--homedir', str(home), '--verify', str(signed), str(release)], check=True)
        path = 'main/binary-amd64/Packages.gz'
        section = release.read_text().split('SHA256:\n', 1)[1].split('\n\n', 1)[0]
        expected = next(line.split()[0] for line in section.splitlines() if line.split()[-1:] == [path])
        archive = download(REPO + '/dists/trixie/' + path)
        if hashlib.sha256(archive).hexdigest() != expected:
            raise RuntimeError('Repository checksum mismatch')
        entries = gzip.decompress(archive).decode().split('\n\n')
        candidates = []
        for entry in entries:
            data = dict(line.split(': ', 1) for line in entry.splitlines() if ': ' in line and not line.startswith(' '))
            if data.get('Package') == 'msodbcsql18':
                candidates.append(data)
        if not candidates:
            raise RuntimeError('msodbcsql18 not found in signed package index')
        def compare(a, b):
            if subprocess.run(['dpkg', '--compare-versions', a['Version'], 'gt', b['Version']]).returncode == 0: return 1
            if subprocess.run(['dpkg', '--compare-versions', a['Version'], 'lt', b['Version']]).returncode == 0: return -1
            return 0
        data = max(candidates, key=functools.cmp_to_key(compare))
        deb = download(REPO + '/' + data['Filename'])
        if hashlib.sha256(deb).hexdigest() != data['SHA256']:
            raise RuntimeError('Driver checksum mismatch')
        package = temp / 'driver.deb'
        package.write_bytes(deb)
        subprocess.run(['dpkg-deb', '-x', str(package), str(ROOT)], check=True)
    library = next((ROOT / 'opt/microsoft/msodbcsql18/lib64').glob('libmsodbcsql-*.so.*'))
    (ROOT / 'odbcinst.ini').write_text('[ODBC Driver 18 for SQL Server]\nDescription=Microsoft ODBC Driver 18 for SQL Server\nDriver=' + str(library) + '\nUsageCount=1\n')
    print('Verified driver installed. Export ODBCSYSINI=' + str(ROOT))

if __name__ == '__main__':
    main()

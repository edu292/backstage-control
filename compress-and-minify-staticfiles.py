from pathlib import Path
from subprocess import run
from re import compile

MINIMUM_ORIGINAL_SIZE_FOR_COMPRESSION = 1400
EXTENSIONS_TO_COMPRESS = {'.css', '.js', '.svg', '.ico'}
EXTENSIONS_TO_MINIFY = {'.css', '.js'}
HASH_REGEX = compile(r'\.[a-zA-Z0-9]{12,}\.')

staticfiles_folder = Path.cwd() / 'staticfiles'
manifest_file = staticfiles_folder / 'staticfiles.json'

for file in staticfiles_folder.rglob('*.*'):
    if file == manifest_file:
        continue

    if not HASH_REGEX.search(file.name):
        file.unlink()
        continue

    if file.stat().st_size < MINIMUM_ORIGINAL_SIZE_FOR_COMPRESSION:
        continue

    extension = file.suffix
    if extension not in EXTENSIONS_TO_COMPRESS:
        continue

    path_to_file = str(file)

    if extension in EXTENSIONS_TO_MINIFY:
        run(['./esbuild', path_to_file, '--minify', f'--outfile={path_to_file}', '--allow-overwrite', '--log-level=error'])

    run(['brotli', '--best', path_to_file])
    run(['gzip', '--best', path_to_file])
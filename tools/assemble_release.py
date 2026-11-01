#!/usr/bin/env python3
"""Public, standard-library-only byte assembler. Contains no rendering/business rules."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path,PurePosixPath
import shutil
import stat
import tempfile
from urllib.request import Request,urlopen
from urllib.parse import urlsplit
import zipfile
from concurrent.futures import ThreadPoolExecutor


def relative(value):
    if not value or '\\' in value or '\0' in value or ':' in value or any(c in value for c in '<>"|?*'):raise ValueError('Invalid path')
    p=PurePosixPath(value)
    if p.is_absolute() or any(s in {'','.','..'} for s in value.split('/')):raise ValueError('Path traversal')
    for s in p.parts:
        if s.rstrip('. ')!=s or s.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]}:raise ValueError('Nonportable path')
    return value


def inside(root,value):
    p=root/relative(value)
    if not p.resolve().is_relative_to(root.resolve()):raise ValueError('Path escapes root')
    return p


def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def verify(path,info):
    if not path.is_file() or path.is_symlink() or path.stat().st_size!=info['bytes'] or sha(path)!=info['sha256']:
        raise ValueError('Missing or changed bytes: '+path.name)


def download(info,dest,local=None):
    if local:
        path=inside(local,info.get('file') or Path(info['path']).name)
        verify(path,info);return path
    url=urlsplit(info['url'])
    if url.scheme!='https' or url.hostname!='github.com' or '/releases/download/' not in url.path:
        raise ValueError('Unregistered release URL')
    request=Request(info['url'],headers={'User-Agent':'midicn-release-assembler'})
    digest=hashlib.sha256();size=0
    with urlopen(request,timeout=60) as response,dest.open('wb') as f:
        while chunk:=response.read(1<<20):
            size+=len(chunk)
            if size>info['bytes']:raise ValueError('Release byte limit exceeded')
            digest.update(chunk);f.write(chunk)
    if size!=info['bytes'] or digest.hexdigest()!=info['sha256']:raise ValueError('Release hash mismatch')
    return dest


def assemble(source,output,local_archives=None,local_files=None):
    source=source.resolve();output=output.resolve()
    if source==output or source.is_relative_to(output):raise ValueError('Output cannot replace the source')
    if output.exists() and any(output.iterdir()):raise ValueError('Output must be empty')
    manifest=json.loads((source/'file-manifest.json').read_text(encoding='utf-8'))
    release=json.loads((source/'release.json').read_text(encoding='utf-8'))
    if manifest.get('schema')!=1 or release.get('schema')!=1:raise ValueError('Unsupported release schema')
    if release.get('manifest_sha256')!=sha(source/'file-manifest.json'):raise ValueError('File manifest digest mismatch')
    files=manifest['files'];folded=set()
    for path,info in files.items():
        relative(path)
        if path.casefold() in folded:raise ValueError('Case-insensitive output collision')
        folded.add(path.casefold())
        if info['bytes']<0 or len(info['sha256'])!=64:raise ValueError('Invalid file record')
    total=sum(i['bytes'] for i in files.values())
    if total>=1_000_000_000:raise ValueError('Published site exceeds capacity')
    output.mkdir(parents=True,exist_ok=True)
    archives=release.get('external_archives',[]);singles=release.get('external_files',[])
    external={s['path'] for s in singles}
    for a in archives:external|={p for p in files if any(p.startswith(prefix) for prefix in a['prefixes'])}
    def copy_runtime(item):
        rel,info=item
        src=inside(source,rel);verify(src,info)
        dst=output/relative(rel);dst.parent.mkdir(parents=True,exist_ok=True);dst=inside(output,rel);shutil.copyfile(src,dst)
    with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(copy_runtime,((p,i) for p,i in files.items() if p not in external)))
    with tempfile.TemporaryDirectory(prefix='midicn-assemble-') as temporary:
        temp=Path(temporary)
        for archive in archives:
            blob=download(archive,temp/relative(archive['file']),local_archives)
            allowed={p for p in files if any(p.startswith(prefix) for prefix in archive['prefixes'])}
            seen=set()
            with zipfile.ZipFile(blob) as z:
                members=[]
                for member in z.infolist():
                    name=relative(member.filename)
                    if member.is_dir():continue
                    mode=member.external_attr>>16
                    if stat.S_IFMT(mode) not in {0,stat.S_IFREG} or member.flag_bits&1:raise ValueError('Archive contains special or encrypted entry')
                    if name not in allowed or name.casefold() in seen:raise ValueError('Unexpected/duplicate archive entry')
                    seen.add(name.casefold());expected=files[name]
                    if member.file_size!=expected['bytes']:raise ValueError('Expanded file size mismatch')
                    members.append(member)
                if seen!={p.casefold() for p in allowed}:raise ValueError('Archive is incomplete')
                def extract(member):
                    name=member.filename;expected=files[name]
                    dst=output/relative(name);dst.parent.mkdir(parents=True,exist_ok=True);dst=inside(output,name)
                    digest=hashlib.sha256();size=0
                    with z.open(member) as reader,dst.open('wb') as writer:
                        while chunk:=reader.read(1<<20):
                            size+=len(chunk)
                            if size>expected['bytes']:raise ValueError('Expanded bytes exceeded record')
                            digest.update(chunk);writer.write(chunk)
                    if size!=expected['bytes'] or digest.hexdigest()!=expected['sha256']:raise ValueError('Expanded hash mismatch')
                with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(extract,members))
        for info in singles:
            rel=info['path']
            if rel not in files or files[rel]['sha256']!=info['sha256'] or files[rel]['bytes']!=info['bytes']:raise ValueError('External file disagrees with manifest')
            blob=download(info,temp/Path(rel).name,local_files)
            dst=inside(output,rel);dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(blob,dst)
    for name in ['file-manifest.json','release.json']:shutil.copyfile(source/name,output/name)
    actual=sum(p.stat().st_size for p in output.rglob('*') if p.is_file())
    if actual>=1_000_000_000:raise ValueError('Complete artifact exceeds Pages capacity')
    print(json.dumps({'site':release['site'],'files':len(files)+2,'bytes':actual,'verified':True}),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--local-archives',type=Path);p.add_argument('--local-files',type=Path)
    args=p.parse_args();assemble(args.source,args.output,args.local_archives,args.local_files)


if __name__=='__main__':main()

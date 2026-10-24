"""Extract a Google Drive download zip into a flat folder, keeping Arabic file names intact.

Usage: python -I -X utf8 scripts/extract_zip.py <zip> <out_dir>
"""
import pathlib
import sys
import zipfile


def entry_name(info: zipfile.ZipInfo) -> str:
    # Without the UTF-8 flag, zipfile decodes names as cp437; undo that.
    if info.flag_bits & 0x800:
        return info.filename
    return info.filename.encode("cp437").decode("utf-8")


def main(zip_path: str, out_dir: str) -> None:
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        entries = [i for i in z.infolist() if not i.is_dir()]
        names = [pathlib.PurePosixPath(entry_name(i)).name for i in entries]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            sys.exit(f"duplicate names in zip, refusing to flatten: {sorted(dupes)}")
        for info, name in zip(entries, names):
            target = out / name
            data = z.read(info)
            if target.exists():
                if target.read_bytes() != data:
                    sys.exit(f"refusing to overwrite {target}: contents differ")
                print(f"{'same':>10}  {name}")
                continue
            target.write_bytes(data)
            print(f"{info.file_size:>10}  {name}")
    print(f"{len(entries)} files -> {out}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

import os
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
BACKUP_DIR = os.path.join(DATA, "backups")
BACKUP_KEEP = 14
FILES = ["bot.db", "favorites.json"]


def make_backup() -> str:
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(BACKUP_DIR, f"bot_backup_{stamp}.zip")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name in FILES:
            full = os.path.join(DATA, name)
            if os.path.exists(full):
                z.write(full, name)
    return path


def prune() -> None:
    backups = sorted(
        (f for f in os.listdir(BACKUP_DIR) if f.endswith(".zip")), reverse=True)
    for old in backups[BACKUP_KEEP:]:
        os.remove(os.path.join(BACKUP_DIR, old))


if __name__ == "__main__":
    p = make_backup()
    prune()
    print(f"Резервну копію збережено: {p}")

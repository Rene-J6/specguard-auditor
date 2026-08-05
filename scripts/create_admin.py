import getpass
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import bootstrap_admin


def main():
    print("SpecGuard first-Admin setup")
    username = input("Username: ").strip()
    full_name = input("Full name: ").strip()
    email = input("Email: ").strip()
    password = getpass.getpass("Password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        print("Passwords do not match.")
        return 1

    success, message = bootstrap_admin(username, password, full_name, email)
    print(message)
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
